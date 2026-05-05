#!/usr/bin/env python3
import argparse
import asyncio
import base64
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import parse_majsoul_har as pmh
from websockets.asyncio.client import connect


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


def choose_target(targets, target_hint=None):
    pages = [target for target in targets if target.get("type") == "page"]
    if target_hint:
        hinted = [
            target
            for target in pages
            if target_hint in target.get("url", "") or target_hint in target.get("title", "")
        ]
        if hinted:
            return hinted[0]
    for target in pages:
        url = target.get("url", "")
        title = target.get("title", "")
        if "maj-soul" in url or "mahjongsoul" in url or "雀魂" in title:
            return target
    for target in pages:
        url = target.get("url", "")
        if url.startswith(("http://", "https://")):
            return target
    if pages:
        return pages[0]
    raise ValueError("no page target found from Chrome DevTools")


class CDPRuntimeClient:
    def __init__(self):
        self.message_id = 0

    async def send(self, ws, method, params=None):
        self.message_id += 1
        msg_id = self.message_id
        await ws.send(json.dumps({
            "id": msg_id,
            "method": method,
            "params": params or {},
        }))
        while True:
            raw = await ws.recv()
            message = json.loads(raw)
            if message.get("id") != msg_id:
                continue
            if "error" in message:
                raise RuntimeError(message["error"])
            return message.get("result", {})

    async def eval_json(self, ws, expression, await_promise=False):
        result = await self.send(ws, "Runtime.evaluate", {
            "expression": expression,
            "awaitPromise": await_promise,
            "returnByValue": True,
        })
        inner = result.get("result", {})
        if "value" not in inner:
            raise RuntimeError(f"missing Runtime.evaluate value: {result}")
        value = inner["value"]
        if isinstance(value, str):
            return json.loads(value)
        return value


def js_string(s):
    return json.dumps(s, ensure_ascii=False)


def build_lobby_call(method_name, payload, timeout_ms):
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return rf"""
new Promise((resolve) => {{
  const timer = setTimeout(() => resolve(JSON.stringify({{
    timeout: true,
    method: {js_string(method_name)}
  }})), {timeout_ms});
  app.NetAgent.sendReq2Lobby('Lobby', {js_string(method_name)}, {payload_json}, (err, res) => {{
    clearTimeout(timer);
    resolve(JSON.stringify({{
      err: err ? String(err) : null,
      res: res || null
    }}));
  }});
}})
"""


def build_lobby_call_start(method_name, payload, token):
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    token_json = js_string(token)
    return rf"""
(() => {{
  const toBase64 = (bytes) => {{
    if (!bytes) return null;
    const chunkSize = 0x8000;
    let binary = '';
    for (let i = 0; i < bytes.length; i += chunkSize) {{
      const chunk = bytes.subarray ? bytes.subarray(i, i + chunkSize) : bytes.slice(i, i + chunkSize);
      binary += String.fromCharCode.apply(null, chunk);
    }}
    return btoa(binary);
  }};
  globalThis.__codexLobbyCalls = globalThis.__codexLobbyCalls || Object.create(null);
  globalThis.__codexLobbyCalls[{token_json}] = {{
    done: false,
    method: {js_string(method_name)},
    started_at: Date.now()
  }};
  app.NetAgent.sendReq2Lobby('Lobby', {js_string(method_name)}, {payload_json}, (err, res) => {{
    let slimData = null;
    if (typeof res?.data === 'string') {{
      slimData = res.data;
    }} else if (res?.data && typeof res.data === 'object' && '_base64' in res.data) {{
      slimData = {{ _base64: res.data._base64, _hex: res.data._hex || null }};
    }} else if (res?.data && typeof res.data === 'object' && typeof res.data.length === 'number') {{
      slimData = {{ _base64: toBase64(res.data) }};
    }}
    const slimRes = !res ? null : {{
      head: res.head || null,
      data: slimData
    }};
    globalThis.__codexLobbyCalls[{token_json}] = {{
      done: true,
      err: err ? String(err) : null,
      res: slimRes,
      finished_at: Date.now()
    }};
  }});
  return JSON.stringify({{token: {token_json}}});
}})()
"""


def build_lobby_call_poll(token):
    token_json = js_string(token)
    return rf"""
(() => {{
  const bucket = globalThis.__codexLobbyCalls || Object.create(null);
  return JSON.stringify(bucket[{token_json}] || null);
}})()
"""


def build_lobby_call_clear(token):
    token_json = js_string(token)
    return rf"""
(() => {{
  if (globalThis.__codexLobbyCalls) {{
    delete globalThis.__codexLobbyCalls[{token_json}];
  }}
  return JSON.stringify({{cleared: true}});
}})()
"""


def decode_game_detail_records(schema, raw_base64):
    raw = base64.b64decode(raw_base64)
    fields = pmh.parse_simple_protobuf(raw)
    wrapped_name = None
    wrapped_body = None
    for field_id, wire_type, value in fields:
        if field_id == 1 and wire_type == 2:
            wrapped_name = value.decode("utf-8", errors="replace")
        elif field_id == 2 and wire_type == 2:
            wrapped_body = value
    payload = {
        "game_detail_records_wrapper": {
            "name": wrapped_name,
            "body_len": len(wrapped_body or b""),
        }
    }
    if wrapped_name == ".lq.GameDetailRecords" and wrapped_body:
        payload["game_detail_records"] = schema.decode_message(wrapped_body, "GameDetailRecords")
    else:
        payload["game_detail_records_decode_error"] = f"unexpected wrapper name: {wrapped_name!r}"
        payload["game_detail_records_raw_base64"] = raw_base64
    return payload


def infer_uuids_from_summary(summary_path, seer_dir, only_four_player):
    summary_rows = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    seer_uuids = {path.name[:-10] for path in Path(seer_dir).glob("*.seer.json")}
    picked = {}
    for row in summary_rows:
        uuid = row.get("uuid")
        if not uuid or uuid not in seer_uuids:
            continue
        if only_four_player and len(row.get("players") or []) != 4:
            continue
        prev = picked.get(uuid)
        if prev is None or (row.get("end_time") or 0) > (prev.get("end_time") or 0):
            picked[uuid] = row
    return [
        row["uuid"]
        for row in sorted(picked.values(), key=lambda item: item.get("end_time") or 0, reverse=True)
    ]


async def fetch_records(args):
    schema = pmh.LiqiSchema(json.loads(Path(args.liqi_json).read_text(encoding="utf-8")))
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    targets = fetch_json(f"http://{args.host}:{args.port}/json")
    target = choose_target(targets, args.target_hint)

    wanted = list(args.uuids or [])
    if not wanted:
        wanted = infer_uuids_from_summary(args.summary_json, args.seer_dir, args.only_four_player)

    print(f"[paipu] target: {target.get('title')}", flush=True)
    print(f"[paipu] url: {target.get('url')}", flush=True)
    print(f"[paipu] output: {outdir}", flush=True)
    print(f"[paipu] uuids: {len(wanted)}", flush=True)

    fetched = []
    failed = []
    async with connect(target["webSocketDebuggerUrl"], max_size=None) as ws:
        client = CDPRuntimeClient()
        await client.send(ws, "Runtime.enable")

        for game_uuid in wanted:
            success = False
            last_error = None
            for attempt in range(1, args.retries + 1):
                try:
                    started = time.time()
                    token = f"fetchGameRecord:{game_uuid}:{int(started * 1000)}:{attempt}"
                    await client.eval_json(
                        ws,
                        build_lobby_call_start(
                            "fetchGameRecord",
                            {
                                "game_uuid": game_uuid,
                                "client_version_string": args.client_version_string,
                            },
                            token,
                        ),
                    )

                    response = None
                    deadline = started + (args.timeout_ms / 1000.0)
                    while time.time() < deadline:
                        polled = await client.eval_json(ws, build_lobby_call_poll(token))
                        if polled and polled.get("done"):
                            response = polled
                            break
                        await asyncio.sleep(args.poll_interval_ms / 1000.0)
                    await client.eval_json(ws, build_lobby_call_clear(token))

                    elapsed_ms = int((time.time() - started) * 1000)
                    if not response:
                        raise TimeoutError(f"fetchGameRecord timeout after {args.timeout_ms}ms")

                    res = (response or {}).get("res") or {}
                    head = res.get("head") or {}
                    data = res.get("data")
                    raw_base64 = None
                    if isinstance(data, dict) and data.get("_base64"):
                        raw_base64 = data["_base64"]
                    elif isinstance(data, str) and data:
                        raw_base64 = data

                    target_path = outdir / f"{game_uuid}.json"
                    existing = {}
                    if target_path.exists():
                        try:
                            existing = json.loads(target_path.read_text(encoding="utf-8"))
                        except Exception:
                            existing = {}

                    output = {
                        "meta": {
                            "method": "fetchGameRecord",
                            "uuid": game_uuid,
                            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "elapsed_ms": elapsed_ms,
                            "attempt": attempt,
                        },
                        "head": head or existing.get("head"),
                        "result": existing.get("result", head.get("result")),
                        "accounts": existing.get("accounts", head.get("accounts")),
                    }
                    if raw_base64:
                        output.update(decode_game_detail_records(schema, raw_base64))
                    else:
                        output["game_detail_records_decode_error"] = "missing data payload"

                    target_path.write_text(
                        json.dumps(output, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    fetched.append({
                        "uuid": game_uuid,
                        "path": str(target_path),
                        "actions": len(((output.get("game_detail_records") or {}).get("actions") or [])),
                    })
                    print(f"[paipu] fetched {game_uuid} actions={fetched[-1]['actions']} attempt={attempt}", flush=True)
                    success = True
                    break
                except Exception as exc:
                    last_error = repr(exc)
                    print(f"[paipu] retry {attempt}/{args.retries} failed for {game_uuid}: {exc}", flush=True)
                    await asyncio.sleep(args.retry_sleep_ms / 1000.0)
            if not success:
                failed.append({"uuid": game_uuid, "error": last_error})

    manifest = {
        "fetched": fetched,
        "failed": failed,
    }
    (outdir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[paipu] success={len(fetched)} failed={len(failed)}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Fetch Majsoul paipu records from the logged-in page and decode GameDetailRecords.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument("--target-hint", help="Substring to match Majsoul tab URL or title")
    parser.add_argument("--liqi-json", default="/Users/bigo/code/mj/liqi.json")
    parser.add_argument("--output-dir", default="/Users/bigo/code/mj/paipu_exports")
    parser.add_argument("--summary-json", default="/Users/bigo/code/mj/paipu_exports/record_list_summary.json")
    parser.add_argument("--seer-dir", default="/Users/bigo/code/mj/seer_exports")
    parser.add_argument("--uuid", dest="uuids", action="append", help="Fetch only the specified game uuid; repeatable")
    parser.add_argument("--only-four-player", action="store_true", default=False)
    parser.add_argument("--client-version-string", default="web-1.0.0")
    parser.add_argument("--timeout-ms", type=int, default=45000)
    parser.add_argument("--poll-interval-ms", type=int, default=200)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-sleep-ms", type=int, default=1500)
    args = parser.parse_args()

    try:
        asyncio.run(fetch_records(args))
    except urllib.error.URLError as exc:
        print(
            "[paipu] 连不上 Chrome DevTools。\n"
            "请先用带调试端口的 Chrome 打开雀魂：\n"
            "\"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome\" "
            "--remote-debugging-port=9222 --user-data-dir=/tmp/majsoul-cdp\n"
            f"原始错误: {exc}",
            flush=True,
        )
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
