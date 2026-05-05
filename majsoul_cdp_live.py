#!/usr/bin/env python3
import argparse
import asyncio
import base64
import datetime as dt
import json
import urllib.error
import urllib.request
from pathlib import Path

import parse_majsoul_har as pmh
from majsoul_live_helper import LiveGameState
from websockets.asyncio.client import connect


def load_schema(liqi_json_path=None, schema_har_path=None):
    if liqi_json_path:
        data = json.loads(Path(liqi_json_path).read_text(encoding="utf-8"))
        return pmh.LiqiSchema(data)
    if schema_har_path:
        har = json.loads(Path(schema_har_path).read_text(encoding="utf-8"))
        return pmh.LiqiSchema(pmh.extract_liqi_schema(har))
    raise ValueError("need --liqi-json or --schema-har to load liqi schema")


def default_liqi_json():
    return str(Path(__file__).with_name("liqi.json"))


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


def decode_cdp_payload(payload):
    try:
        return base64.b64decode(payload, validate=True)
    except Exception:
        return payload.encode("latin1")


class CDPClient:
    def __init__(self, dump_snapshot=False, debug_log_path=None):
        self.message_id = 0
        self.pending = {}
        self.game_request_ids = set()
        self.dump_snapshot = dump_snapshot
        self.action_index = 0
        self.debug_log_path = Path(debug_log_path) if debug_log_path else None

    def log_debug(self, record):
        if not self.debug_log_path:
            return
        payload = {
            "ts": dt.datetime.now().isoformat(timespec="seconds"),
            **record,
        }
        with self.debug_log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            fh.write("\n")

    def looks_like_liqi_frame(self, raw):
        if not raw:
            return False
        try:
            frame_type, _request_id_num, method_name, _body = pmh.parse_frame(raw)
        except Exception:
            return False
        if frame_type not in (1, 2, 3):
            return False
        if method_name.startswith(".lq.") or method_name == ".lq.ActionPrototype":
            return True
        return frame_type == 1

    async def send(self, ws, method, params=None):
        self.message_id += 1
        message = {
            "id": self.message_id,
            "method": method,
            "params": params or {},
        }
        future = asyncio.get_running_loop().create_future()
        self.pending[self.message_id] = future
        await ws.send(json.dumps(message))
        return await future

    async def send_nowait(self, ws, method, params=None):
        self.message_id += 1
        message = {
            "id": self.message_id,
            "method": method,
            "params": params or {},
        }
        await ws.send(json.dumps(message))

    async def handle_message(self, raw_message, state, schema):
        message = json.loads(raw_message)

        if "id" in message:
            future = self.pending.pop(message["id"], None)
            if future and not future.done():
                if "error" in message:
                    future.set_exception(RuntimeError(message["error"]))
                else:
                    future.set_result(message.get("result", {}))
            return

        event_method = message.get("method")
        params = message.get("params", {})

        if event_method == "Network.webSocketCreated":
            url = params.get("url", "")
            request_id = params.get("requestId")
            if "game-gateway" in url:
                self.game_request_ids.add(request_id)
                self.log_debug({
                    "kind": "websocket_created",
                    "request_id": request_id,
                    "url": url,
                })
                print(f"[cdp] game websocket: {url}", flush=True)
            return

        if event_method not in ("Network.webSocketFrameSent", "Network.webSocketFrameReceived"):
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
            self.log_debug({
                "kind": "websocket_detected_from_frames",
                "request_id": request_id,
            })
            print(f"[cdp] detected majsoul websocket from frames: {request_id}", flush=True)

        try:
            frame_type, request_id_num, method_name, body = pmh.parse_frame(raw)
        except Exception:
            return

        if frame_type == 2:
            decoded = pmh.decode_message_body(schema, method_name, body, frame_type)
            state.apply_request(request_id_num, method_name, decoded)
            self.log_debug({
                "kind": "request",
                "request_id": request_id_num,
                "method": method_name,
                "decoded": decoded,
            })
            return
        if frame_type == 3:
            state.apply_response(request_id_num, schema, body)
            self.log_debug({
                "kind": "response",
                "request_id": request_id_num,
                "method": state.pending_requests.get(request_id_num),
            })
            return
        if frame_type == 1 and method_name == ".lq.ActionPrototype":
            action = state.decode_action(schema, body)
            self.action_index += 1
            suggestion = state.apply_action(action, self.action_index)
            snapshot = getattr(state, "last_decision_snapshot", None)
            self.log_debug({
                "kind": "action",
                "event_index": self.action_index,
                "action_name": action.get("name"),
                "action_data": action.get("data"),
                "self_seat": state.self_seat,
                "round": state.round_label,
                "hand_count": len(state.hand),
                "open_melds": state.open_melds,
                "effective_hand_tiles": state.effective_hand_tiles(),
                "suggestion_emitted": bool(suggestion),
                "suggestion_trigger": snapshot.get("trigger") if snapshot else None,
                "confidence": snapshot.get("confidence") if snapshot else None,
            })
            if suggestion:
                print("", flush=True)
                print(suggestion, flush=True)
                if self.dump_snapshot and snapshot and snapshot.get("confidence", 1.0) < 0.55:
                    print("[snapshot]", flush=True)
                    print(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")), flush=True)
                    print("[/snapshot]", flush=True)
                print("[live] 已继续监听，等你的下一个决策点再输出。", flush=True)


async def watch_live(args):
    schema = load_schema(args.liqi_json, args.schema_har)
    targets = fetch_json(f"http://{args.host}:{args.port}/json")
    target = choose_target(targets, args.target_hint)
    page_ws = target["webSocketDebuggerUrl"]
    state = LiveGameState()

    print(f"[cdp] target: {target.get('title')}", flush=True)
    print(f"[cdp] url: {target.get('url')}", flush=True)

    async with connect(page_ws, max_size=None) as ws:
        client = CDPClient(
            dump_snapshot=args.dump_snapshot,
            debug_log_path=args.debug_log,
        )
        await client.send_nowait(ws, "Network.enable")

        while True:
            raw_message = await ws.recv()
            try:
                await client.handle_message(raw_message, state, schema)
            except Exception as exc:
                print(f"[cdp] handler error: {exc!r}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Watch Majsoul live via Chrome DevTools Protocol.")
    parser.add_argument("--host", default="127.0.0.1", help="Chrome DevTools host")
    parser.add_argument("--port", type=int, default=9222, help="Chrome DevTools port")
    parser.add_argument("--target-hint", help="Substring to match Majsoul tab URL or title")
    parser.add_argument("--schema-har", help="HAR file that contains liqi.json")
    parser.add_argument("--liqi-json", help="Direct path to liqi.json")
    parser.add_argument("--dump-snapshot", action="store_true", help="Print decision snapshot JSON when confidence is low")
    parser.add_argument("--debug-log", help="Write realtime debug records as JSONL")
    args = parser.parse_args()

    if not args.liqi_json and not args.schema_har:
        candidate = Path(default_liqi_json())
        if candidate.exists():
            args.liqi_json = str(candidate)

    try:
        asyncio.run(watch_live(args))
    except urllib.error.URLError as exc:
        print(
            "[cdp] 连不上 Chrome DevTools。\n"
            "请先用带调试端口的 Chrome 启动雀魂，例如：\n"
            "\"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome\" "
            "--remote-debugging-port=9222 --user-data-dir=/tmp/majsoul-cdp\n"
            "然后确认这个命令有输出：\n"
            "curl http://127.0.0.1:9222/json/version\n"
            f"原始错误: {exc}",
            flush=True,
        )
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
