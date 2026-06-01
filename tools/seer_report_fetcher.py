#!/usr/bin/env python3
import argparse
import asyncio
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from majsoul_cdp_live import choose_target
from websockets.asyncio.client import connect


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


class CDPRuntimeClient:
    def __init__(self):
        self.message_id = 0
        self.pending = {}

    async def send(self, ws, method, params=None):
        self.message_id += 1
        msg_id = self.message_id
        future = asyncio.get_running_loop().create_future()
        self.pending[msg_id] = future
        await ws.send(json.dumps({
            "id": msg_id,
            "method": method,
            "params": params or {},
        }))
        while True:
            raw = await ws.recv()
            message = json.loads(raw)
            if "id" not in message:
                continue
            future = self.pending.pop(message["id"], None)
            if not future:
                continue
            if "error" in message:
                future.set_exception(RuntimeError(message["error"]))
            else:
                future.set_result(message.get("result", {}))
            if message["id"] == msg_id:
                return await future

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


def build_lobby_call(method_name, payload):
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return rf"""
new Promise((resolve) => {{
  app.NetAgent.sendReq2Lobby('Lobby', {js_string(method_name)}, {payload_json}, (err, res) => {{
    resolve(JSON.stringify({{
      err: err ? String(err) : null,
      res: res || null
    }}));
  }});
}})
"""


async def fetch_seer_data(args):
    targets = fetch_json(f"http://{args.host}:{args.port}/json")
    target = choose_target(targets, args.target_hint)
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"[seer] target: {target.get('title')}", flush=True)
    print(f"[seer] url: {target.get('url')}", flush=True)
    print(f"[seer] outdir: {outdir}", flush=True)

    async with connect(target["webSocketDebuggerUrl"], max_size=None) as ws:
        client = CDPRuntimeClient()
        await client.send(ws, "Runtime.enable")

        info = await client.eval_json(ws, build_lobby_call("fetchSeerInfo", {}), await_promise=True)
        report_list = await client.eval_json(ws, build_lobby_call("fetchSeerReportList", {}), await_promise=True)

        (outdir / "seer_info.json").write_text(
            json.dumps(info, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (outdir / "seer_report_list.json").write_text(
            json.dumps(report_list, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        report_list_items = ((report_list or {}).get("res") or {}).get("seer_report_list") or []
        wanted = set(args.uuids or [])
        if not wanted:
            wanted = {item.get("uuid") for item in report_list_items if item.get("uuid")}

        fetched = []
        for uuid in report_list_items:
            game_uuid = uuid.get("uuid")
            if not game_uuid or game_uuid not in wanted:
                continue
            payload = {"uuid": game_uuid}
            report = await client.eval_json(ws, build_lobby_call("fetchSeerReport", payload), await_promise=True)
            target_path = outdir / f"{game_uuid}.seer.json"
            target_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            fetched.append(str(target_path))
            print(f"[seer] fetched {game_uuid}", flush=True)

        manifest = {
            "seer_info_file": str(outdir / "seer_info.json"),
            "seer_report_list_file": str(outdir / "seer_report_list.json"),
            "fetched_reports": fetched,
        }
        (outdir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print(f"[seer] reports: {len(fetched)}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Fetch Majsoul Seer (MAKA) reports from the logged-in page.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument("--target-hint", help="Substring to match Majsoul tab URL or title")
    parser.add_argument("--output-dir", default="/Users/bigo/code/mj/data/seer_exports")
    parser.add_argument("--uuid", dest="uuids", action="append", help="Fetch only the specified game uuid; repeatable")
    args = parser.parse_args()

    try:
        asyncio.run(fetch_seer_data(args))
    except urllib.error.URLError as exc:
        print(
            "[seer] 连不上 Chrome DevTools。\n"
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
