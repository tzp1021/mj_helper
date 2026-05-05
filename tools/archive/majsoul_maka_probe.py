#!/usr/bin/env python3
import argparse
import asyncio
import datetime as dt
import json
import urllib.error
from pathlib import Path

import parse_majsoul_har as pmh
from majsoul_cdp_live import choose_target, decode_cdp_payload, default_liqi_json, fetch_json
from majsoul_paipu_sniffer import load_schema
from websockets.asyncio.client import connect


WS_ANALYSIS_HINTS = (
    "analysis",
    "analys",
    "record",
    "gameRecord",
    "maka",
    "seer",
    "review",
    "record_detail",
    "paipu",
)

HTTP_ANALYSIS_HINTS = (
    "analysis",
    "analys",
    "record",
    "maka",
    "review",
    "paipu",
)


def now_ts():
    return dt.datetime.now().isoformat(timespec="seconds")


def safe_jsonable(payload):
    try:
        json.dumps(payload, ensure_ascii=False)
        return payload
    except Exception:
        return repr(payload)


def looks_interesting_url(url):
    lower = (url or "").lower()
    if "maj-soul" not in lower and "mahjongsoul" not in lower:
        return False
    return any(hint in lower for hint in HTTP_ANALYSIS_HINTS)


def looks_interesting_method(method_name):
    if not method_name.startswith(".lq.Lobby."):
        return False
    lower = method_name.lower()
    return any(hint.lower() in lower for hint in WS_ANALYSIS_HINTS)


class MakaProbe:
    def __init__(self, schema, output_path, include_all_lobby=False, body_limit=20000):
        self.schema = schema
        self.output_path = Path(output_path)
        self.include_all_lobby = include_all_lobby
        self.body_limit = body_limit
        self.message_id = 0
        self.pending_calls = {}
        self.pending_rpc_methods = {}
        self.game_request_ids = set()
        self.http_candidates = {}
        self.http_logged = set()

    def write_record(self, payload):
        row = {"ts": now_ts(), **payload}
        with self.output_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            fh.write("\n")

    async def send(self, ws, method, params=None):
        self.message_id += 1
        msg_id = self.message_id
        future = asyncio.get_running_loop().create_future()
        self.pending_calls[msg_id] = future
        await ws.send(json.dumps({
            "id": msg_id,
            "method": method,
            "params": params or {},
        }))
        return await future

    async def send_nowait(self, ws, method, params=None):
        self.message_id += 1
        await ws.send(json.dumps({
            "id": self.message_id,
            "method": method,
            "params": params or {},
        }))

    def wants_ws_method(self, method_name):
        if self.include_all_lobby and method_name.startswith(".lq.Lobby."):
            return True
        return looks_interesting_method(method_name)

    def wants_notify_method(self, method_name):
        lower = method_name.lower()
        return (
            method_name.startswith(".lq.Notify")
            and ("seer" in lower or "report" in lower or "analysis" in lower or "analys" in lower)
        )

    def remember_http_candidate(self, request_id, meta):
        existing = self.http_candidates.get(request_id, {})
        existing.update(meta)
        self.http_candidates[request_id] = existing

    async def maybe_fetch_http_body(self, ws, request_id):
        if request_id in self.http_logged:
            return
        meta = self.http_candidates.get(request_id)
        if not meta:
            return
        self.http_logged.add(request_id)
        try:
            body_result = await self.send(ws, "Network.getResponseBody", {"requestId": request_id})
        except Exception as exc:
            self.write_record({
                "kind": "http_body_error",
                "request_id": request_id,
                "meta": meta,
                "error": repr(exc),
            })
            return

        body = body_result.get("body", "")
        if body_result.get("base64Encoded"):
            body = f"[base64:{len(body)} chars]"
        if isinstance(body, str) and len(body) > self.body_limit:
            body = body[: self.body_limit] + "...[truncated]"

        self.write_record({
            "kind": "http_response_body",
            "request_id": request_id,
            "meta": meta,
            "body": body,
        })
        print(f"[probe] http body {meta.get('url')}", flush=True)

    def looks_like_liqi_frame(self, raw):
        if not raw:
            return False
        try:
            frame_type, _rpc_id, method_name, _body = pmh.parse_frame(raw)
        except Exception:
            return False
        if frame_type not in (1, 2, 3):
            return False
        return method_name.startswith(".lq.") or method_name == ".lq.ActionPrototype"

    async def handle_message(self, ws, raw_message):
        message = json.loads(raw_message)

        if "id" in message:
            future = self.pending_calls.pop(message["id"], None)
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
                print(f"[probe] websocket: {url}", flush=True)
            return

        if event_method == "Network.requestWillBeSent":
            request = params.get("request", {})
            url = request.get("url", "")
            request_id = params.get("requestId")
            resource_type = params.get("type", "")
            if resource_type in ("Fetch", "XHR") and looks_interesting_url(url):
                self.remember_http_candidate(request_id, {
                    "url": url,
                    "method": request.get("method"),
                    "resource_type": resource_type,
                })
                self.write_record({
                    "kind": "http_request",
                    "request_id": request_id,
                    "url": url,
                    "method": request.get("method"),
                    "resource_type": resource_type,
                    "post_data": request.get("postData"),
                })
                print(f"[probe] http request {url}", flush=True)
            return

        if event_method == "Network.responseReceived":
            request_id = params.get("requestId")
            response = params.get("response", {})
            if request_id in self.http_candidates:
                self.remember_http_candidate(request_id, {
                    "status": response.get("status"),
                    "mime_type": response.get("mimeType"),
                })
                return

        if event_method == "Network.loadingFinished":
            request_id = params.get("requestId")
            if request_id in self.http_candidates:
                await self.maybe_fetch_http_body(ws, request_id)
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
            print(f"[probe] detected majsoul websocket from frames: {request_id}", flush=True)

        try:
            frame_type, rpc_id, method_name, body = pmh.parse_frame(raw)
        except Exception:
            return

        if frame_type == 2:
            decoded = pmh.decode_message_body(self.schema, method_name, body, frame_type)
            self.pending_rpc_methods[rpc_id] = method_name
            if self.wants_ws_method(method_name):
                self.write_record({
                    "kind": "ws_request",
                    "rpc_id": rpc_id,
                    "method": method_name,
                    "decoded": safe_jsonable(decoded),
                })
                print(f"[probe] ws request {method_name}", flush=True)
            return

        if frame_type == 3:
            request_method = self.pending_rpc_methods.get(rpc_id, "")
            if not request_method or not self.wants_ws_method(request_method):
                return
            decoded = pmh.decode_message_body(self.schema, request_method, body, frame_type)
            self.write_record({
                "kind": "ws_response",
                "rpc_id": rpc_id,
                "method": request_method,
                "decoded": safe_jsonable(decoded),
            })
            print(f"[probe] ws response {request_method}", flush=True)
            return

        if frame_type == 1 and self.wants_notify_method(method_name):
            decoded = pmh.decode_message_body(self.schema, method_name, body, frame_type)
            self.write_record({
                "kind": "ws_notify",
                "method": method_name,
                "decoded": safe_jsonable(decoded),
            })
            print(f"[probe] ws notify {method_name}", flush=True)


async def watch(args):
    schema = load_schema(args.liqi_json)
    targets = fetch_json(f"http://{args.host}:{args.port}/json")
    target = choose_target(targets, args.target_hint)
    print(f"[probe] target: {target.get('title')}", flush=True)
    print(f"[probe] url: {target.get('url')}", flush=True)
    print(f"[probe] output: {args.output}", flush=True)

    async with connect(target["webSocketDebuggerUrl"], max_size=None) as ws:
        probe = MakaProbe(
            schema=schema,
            output_path=args.output,
            include_all_lobby=args.include_all_lobby,
            body_limit=args.body_limit,
        )
        await probe.send_nowait(ws, "Network.enable")
        while True:
            raw_message = await ws.recv()
            await probe.handle_message(ws, raw_message)


def main():
    parser = argparse.ArgumentParser(description="Broader Majsoul probe for paipu / MAKA analysis traffic.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument("--target-hint", help="Substring to match Majsoul tab URL or title")
    parser.add_argument("--liqi-json", default=default_liqi_json(), help="Path to liqi.json")
    parser.add_argument("--output", default="/Users/bigo/code/mj/maka_probe.jsonl", help="JSONL output path")
    parser.add_argument("--include-all-lobby", action="store_true", help="Capture all .lq.Lobby.* websocket methods")
    parser.add_argument("--body-limit", type=int, default=20000, help="Max chars to keep for HTTP response body")
    args = parser.parse_args()

    try:
        asyncio.run(watch(args))
    except urllib.error.URLError as exc:
        print(
            "[probe] 连不上 Chrome DevTools。\n"
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
