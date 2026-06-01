#!/usr/bin/env python3
import argparse
import asyncio
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fetch_paipu_records import (  # type: ignore
    CDPRuntimeClient,
    choose_target,
    decode_game_detail_records,
    fetch_json,
)
import parse_majsoul_har as pmh  # type: ignore
from websockets.asyncio.client import connect


def parse_day_bound(text: str, end: bool, tz_name: str) -> int:
    tz = ZoneInfo(tz_name)
    dt = datetime.strptime(text, "%Y-%m-%d")
    if end:
        dt = dt.replace(hour=23, minute=59, second=59)
    return int(dt.replace(tzinfo=tz).timestamp())


async def lobby_call(client, ws, method_name, payload, timeout_ms, poll_interval_ms):
    token = f"{method_name}:{int(time.time() * 1000)}"
    await client.eval_json(
        ws,
        build_lobby_call_start_generic(method_name, payload, token),
    )
    response = None
    deadline = time.time() + (timeout_ms / 1000.0)
    while time.time() < deadline:
        polled = await client.eval_json(ws, build_lobby_call_poll_generic(token))
        if polled and polled.get("done"):
            response = polled
            break
        await asyncio.sleep(poll_interval_ms / 1000.0)
    await client.eval_json(ws, build_lobby_call_clear_generic(token))
    if not response:
        raise TimeoutError(f"{method_name} timeout after {timeout_ms}ms")
    if response.get("err"):
        raise RuntimeError(f"{method_name} failed: {response['err']}")
    return response.get("res") or {}


def js_string(s):
    return json.dumps(s, ensure_ascii=False)


def build_lobby_call_start_generic(method_name, payload, token):
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
  const slim = (value) => {{
    if (value == null) return value;
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return value;
    if (Array.isArray(value)) return value.map(slim);
    if (typeof value === 'object' && typeof value.length === 'number' && typeof value.BYTES_PER_ELEMENT === 'number') {{
      return {{ _base64: toBase64(value) }};
    }}
    if (typeof value === 'object') {{
      const out = {{}};
      for (const [k, v] of Object.entries(value)) out[k] = slim(v);
      return out;
    }}
    return String(value);
  }};
  globalThis.__codexLobbyCalls = globalThis.__codexLobbyCalls || Object.create(null);
  globalThis.__codexLobbyCalls[{token_json}] = {{
    done: false,
    method: {js_string(method_name)},
    started_at: Date.now()
  }};
  app.NetAgent.sendReq2Lobby('Lobby', {js_string(method_name)}, {payload_json}, (err, res) => {{
    globalThis.__codexLobbyCalls[{token_json}] = {{
      done: true,
      err: err ? String(err) : null,
      res: slim(res),
      finished_at: Date.now()
    }};
  }});
  return JSON.stringify({{token: {token_json}}});
}})()
"""


def build_lobby_call_poll_generic(token):
    token_json = js_string(token)
    return rf"""
(() => {{
  const bucket = globalThis.__codexLobbyCalls || Object.create(null);
  return JSON.stringify(bucket[{token_json}] || null);
}})()
"""


def build_lobby_call_clear_generic(token):
    token_json = js_string(token)
    return rf"""
(() => {{
  if (globalThis.__codexLobbyCalls) delete globalThis.__codexLobbyCalls[{token_json}];
  return JSON.stringify({{cleared: true}});
}})()
"""


def summarize_entry(entry):
    players = []
    for row in entry.get("players") or []:
        players.append({
            "seat": row.get("seat"),
            "rank": row.get("rank"),
            "nickname": row.get("nickname"),
            "account_id": row.get("account_id"),
            "point": row.get("point"),
        })
    return {
        "uuid": entry.get("uuid"),
        "start_time": entry.get("start_time"),
        "end_time": entry.get("end_time"),
        "tag": entry.get("tag"),
        "subtag": entry.get("subtag"),
        "standard_rule": entry.get("standard_rule"),
        "players": players,
    }


async def fetch_range(args):
    schema = pmh.LiqiSchema(json.loads(Path(args.liqi_json).read_text(encoding="utf-8")))
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    begin_ts = parse_day_bound(args.begin_date, end=False, tz_name=args.timezone)
    end_ts = parse_day_bound(args.end_date, end=True, tz_name=args.timezone)

    targets = fetch_json(f"http://{args.host}:{args.port}/json")
    target = choose_target(targets, args.target_hint)
    print(f"[range] target: {target.get('title')}", flush=True)
    print(f"[range] url: {target.get('url')}", flush=True)
    print(f"[range] output: {outdir}", flush=True)
    print(f"[range] window: {args.begin_date} .. {args.end_date} ({args.timezone})", flush=True)

    async with connect(target["webSocketDebuggerUrl"], max_size=None) as ws:
        client = CDPRuntimeClient()
        await client.send(ws, "Runtime.enable")

        list_res = await lobby_call(
            client,
            ws,
            "fetchGameRecordListV2",
            {
                "tag": args.tag,
                "begin_time": begin_ts,
                "end_time": end_ts,
            },
            args.timeout_ms,
            args.poll_interval_ms,
        )
        list_head = list_res.get("head") or list_res
        iterator = list_head.get("iterator")
        if not iterator:
            raise RuntimeError(f"fetchGameRecordListV2 returned no iterator: {list_head}")

        entries = []
        while True:
            page_res = await lobby_call(
                client,
                ws,
                "fetchNextGameRecordList",
                {
                    "iterator": iterator,
                    "count": args.page_size,
                },
                args.timeout_ms,
                args.poll_interval_ms,
            )
            page = page_res.get("head") or page_res
            batch = page.get("entries") or []
            entries.extend(batch)
            print(f"[range] page entries={len(batch)} total={len(entries)} next={page.get('next')}", flush=True)
            if not page.get("next"):
                break

        filtered = []
        for entry in entries:
            players = entry.get("players") or []
            if args.only_four_player and len(players) != 4:
                continue
            filtered.append(entry)

        summary = [summarize_entry(entry) for entry in filtered]
        (outdir / "record_list_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[range] kept {len(summary)} records after filtering", flush=True)

        fetched = []
        failed = []
        for entry in filtered:
            game_uuid = entry.get("uuid")
            if not game_uuid:
                continue
            try:
                started = time.time()
                res = await lobby_call(
                    client,
                    ws,
                    "fetchGameRecord",
                    {
                        "game_uuid": game_uuid,
                        "client_version_string": args.client_version_string,
                    },
                    args.record_timeout_ms,
                    args.poll_interval_ms,
                )
                elapsed_ms = int((time.time() - started) * 1000)
                head = res.get("head") or res
                data = res.get("data")
                raw_base64 = None
                if isinstance(data, dict) and data.get("_base64"):
                    raw_base64 = data["_base64"]
                elif isinstance(data, str) and data:
                    raw_base64 = data

                output = {
                    "meta": {
                        "method": "fetchGameRecord",
                        "uuid": game_uuid,
                        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "elapsed_ms": elapsed_ms,
                        "range": {
                            "begin_date": args.begin_date,
                            "end_date": args.end_date,
                            "timezone": args.timezone,
                        },
                    },
                    "head": head,
                    "result": head.get("result"),
                    "accounts": head.get("accounts"),
                }
                if raw_base64:
                    output.update(decode_game_detail_records(schema, raw_base64))
                else:
                    output["game_detail_records_decode_error"] = "missing data payload"

                target_path = outdir / f"{game_uuid}.json"
                target_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
                actions = len(((output.get("game_detail_records") or {}).get("actions") or []))
                fetched.append({"uuid": game_uuid, "file": str(target_path), "actions": actions})
                print(f"[range] fetched {game_uuid} actions={actions}", flush=True)
            except Exception as exc:
                failed.append({"uuid": game_uuid, "error": repr(exc)})
                print(f"[range] failed {game_uuid}: {exc}", flush=True)

    manifest = {
        "begin_date": args.begin_date,
        "end_date": args.end_date,
        "timezone": args.timezone,
        "count": len(fetched),
        "failed_count": len(failed),
        "files": fetched,
        "failed": failed,
    }
    (outdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[range] success={len(fetched)} failed={len(failed)}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Fetch Majsoul paipu records for a date range from the logged-in page.")
    parser.add_argument("--begin-date", required=True, help="YYYY-MM-DD, inclusive")
    parser.add_argument("--end-date", required=True, help="YYYY-MM-DD, inclusive")
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument("--target-hint", help="Substring to match Majsoul tab URL or title")
    parser.add_argument("--liqi-json", default="/Users/bigo/code/mj/liqi.json")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--tag", type=int, default=0)
    parser.add_argument("--only-four-player", action="store_true", default=True)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--client-version-string", default="web-1.0.0")
    parser.add_argument("--timeout-ms", type=int, default=20000)
    parser.add_argument("--record-timeout-ms", type=int, default=45000)
    parser.add_argument("--poll-interval-ms", type=int, default=200)
    args = parser.parse_args()

    try:
        asyncio.run(fetch_range(args))
    except urllib.error.URLError as exc:
        print(
            "[range] 连不上 Chrome DevTools。\n"
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
