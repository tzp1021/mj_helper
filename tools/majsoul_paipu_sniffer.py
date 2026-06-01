#!/usr/bin/env python3
import argparse
import asyncio
import base64
import datetime as dt
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import parse_majsoul_har as pmh
from majsoul_cdp_live import choose_target, decode_cdp_payload, default_liqi_json, fetch_json
from websockets.asyncio.client import connect


DEFAULT_METHOD_KEYWORDS = (
    "fetchGameRecord",
    "fetchGameRecordList",
    "fetchNextGameRecordList",
    "fetchCollectedGameRecordList",
    "fetchGameRecordsDetail",
    "readGameRecord",
    "fetchSimulationGameRecord",
    "fetchCustomizedContestGameRecords",
    "fetchAccountGameHuRecords",
)


def load_schema(liqi_json_path=None):
    if not liqi_json_path:
        liqi_json_path = default_liqi_json()
    data = json.loads(Path(liqi_json_path).read_text(encoding="utf-8"))
    return pmh.LiqiSchema(data)


def now_ts():
    return dt.datetime.now().isoformat(timespec="seconds")


def method_matches(method_name, keywords):
    return any(keyword in method_name for keyword in keywords)


class PaipuSniffer:
    def __init__(self, schema, output_path, keywords):
        self.schema = schema
        self.output_path = Path(output_path)
        self.keywords = tuple(keywords)
        self.message_id = 0
        self.pending = {}
        self.game_request_ids = set()

    async def send_nowait(self, ws, method, params=None):
        self.message_id += 1
        await ws.send(json.dumps({
            "id": self.message_id,
            "method": method,
            "params": params or {},
        }))

    def write_record(self, payload):
        row = {
            "ts": now_ts(),
            **payload,
        }
        with self.output_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            fh.write("\n")

    def looks_like_liqi_frame(self, raw):
        if not raw:
            return False
        try:
            frame_type, _rid, method_name, _body = pmh.parse_frame(raw)
        except Exception:
            return False
        if frame_type not in (1, 2, 3):
            return False
        return method_name.startswith(".lq.") or method_name == ".lq.ActionPrototype"

    async def handle_message(self, raw_message):
        message = json.loads(raw_message)
        if "id" in message:
            return

        event_method = message.get("method")
        if event_method not in ("Network.webSocketCreated", "Network.webSocketFrameSent", "Network.webSocketFrameReceived"):
            return

        params = message.get("params", {})
        if event_method == "Network.webSocketCreated":
            url = params.get("url", "")
            request_id = params.get("requestId")
            if "game-gateway" in url:
                self.game_request_ids.add(request_id)
                print(f"[paipu] websocket: {url}", flush=True)
            return

        request_id = params.get("requestId")
        payload = params.get("response", {}).get("payloadData", "")
        raw = decode_cdp_payload(payload)
        if not raw:
            return

        if request_id not in self.game_request_ids:
            if not self.looks_like_liqi_frame(raw):
                return
            self.game_request_ids.add(request_id)
            print(f"[paipu] detected majsoul websocket from frames: {request_id}", flush=True)

        try:
            frame_type, rpc_id, method_name, body = pmh.parse_frame(raw)
        except Exception:
            return

        if frame_type == 2:
            decoded = pmh.decode_message_body(self.schema, method_name, body, frame_type)
            self.pending[rpc_id] = method_name
            if method_matches(method_name, self.keywords):
                self.write_record({
                    "kind": "request",
                    "rpc_id": rpc_id,
                    "method": method_name,
                    "decoded": decoded,
                })
                print(f"[paipu] request {method_name}", flush=True)
            return

        if frame_type == 3:
            request_method = self.pending.get(rpc_id, "")
            if not request_method or not method_matches(request_method, self.keywords):
                return
            decoded = pmh.decode_message_body(self.schema, request_method, body, frame_type)
            self.write_record({
                "kind": "response",
                "rpc_id": rpc_id,
                "method": request_method,
                "decoded": decoded,
            })
            print(f"[paipu] response {request_method}", flush=True)


async def watch(args):
    schema = load_schema(args.liqi_json)
    targets = fetch_json(f"http://{args.host}:{args.port}/json")
    target = choose_target(targets, args.target_hint)
    print(f"[paipu] target: {target.get('title')}", flush=True)
    print(f"[paipu] url: {target.get('url')}", flush=True)
    print(f"[paipu] output: {args.output}", flush=True)

    async with connect(target["webSocketDebuggerUrl"], max_size=None) as ws:
        sniffer = PaipuSniffer(schema, args.output, args.keywords)
        await sniffer.send_nowait(ws, "Network.enable")
        while True:
            raw_message = await ws.recv()
            await sniffer.handle_message(raw_message)


def main():
    parser = argparse.ArgumentParser(description="Sniff Majsoul paipu-related lobby RPCs via Chrome DevTools.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument("--target-hint", help="Substring to match Majsoul tab URL or title")
    parser.add_argument("--liqi-json", default=default_liqi_json(), help="Path to liqi.json")
    parser.add_argument("--output", default="/Users/bigo/code/mj/data/paipu_sniff.jsonl", help="JSONL output path")
    parser.add_argument(
        "--keywords",
        nargs="*",
        default=list(DEFAULT_METHOD_KEYWORDS),
        help="Method substrings to capture",
    )
    args = parser.parse_args()

    try:
        asyncio.run(watch(args))
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
