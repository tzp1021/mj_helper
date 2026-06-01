#!/usr/bin/env python3
"""Resolve logical Majsoul asset paths to real URLs via the live page's Laya URL formatter."""

from __future__ import annotations

import argparse
import asyncio
import json
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from websockets.asyncio.client import connect


def fetch_json(url: str) -> list[dict]:
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def choose_target(targets: list[dict], target_hint: str | None = None) -> dict:
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
        if "maj-soul" in url or "雀魂" in title:
            return target
    raise ValueError("no Majsoul page target found")


async def resolve_paths(page_ws: str, paths: list[str]) -> dict[str, str]:
    expression = """
    (paths => {
      const out = {};
      for (const p of paths) {
        try {
          out[p] = (globalThis.Laya && Laya.URL && Laya.URL.formatURL)
            ? Laya.URL.formatURL(p)
            : null;
        } catch (e) {
          out[p] = null;
        }
      }
      return out;
    })
    """
    async with connect(page_ws, max_size=None) as ws:
        await ws.send(
            json.dumps(
                {
                    "id": 1,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": expression,
                        "awaitPromise": False,
                    },
                }
            )
        )
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("id") == 1:
                object_id = msg["result"]["result"]["objectId"]
                break

        await ws.send(
            json.dumps(
                {
                    "id": 2,
                    "method": "Runtime.callFunctionOn",
                    "params": {
                        "objectId": object_id,
                        "functionDeclaration": "function(paths) { return this(paths); }",
                        "arguments": [{"value": paths}],
                        "returnByValue": True,
                    },
                }
            )
        )
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("id") == 2:
                return msg["result"]["result"]["value"]


def load_resversion(path: Path | None) -> dict[str, dict]:
    if not path:
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("res", {})


def fallback_url_for_path(path: str, res_map: dict[str, dict], base_url: str) -> str | None:
    # Character portraits sometimes need lang/base or lang/base_q7 resources even when
    # the logical path starts with chs_t/.
    if path.startswith("chs_t/extendRes/charactor/"):
        rel = path[len("chs_t/") :]
        for candidate in [f"lang/base/{rel}", f"lang/base_q7/{rel}"]:
            meta = res_map.get(candidate)
            if meta and meta.get("prefix"):
                return f"{base_url.rstrip('/')}/{meta['prefix']}/{candidate}"
    return None


def looks_unresolved(path: str, url: str | None) -> bool:
    if not url:
        return True
    parsed = urlparse(url)
    return parsed.path.endswith(path)


async def main_async(args) -> int:
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    assets = manifest.get("assets", [])
    paths = [asset["path"] for asset in assets if asset.get("path")]
    res_map = load_resversion(args.resversion)
    base_url = manifest.get("base_url") or "https://game.maj-soul.com/1/"

    targets = fetch_json(f"http://{args.host}:{args.port}/json")
    target = choose_target(targets, args.target_hint)
    resolved_map: dict[str, str] = {}

    batch_size = args.batch_size
    for start in range(0, len(paths), batch_size):
        chunk = paths[start : start + batch_size]
        resolved_map.update(await resolve_paths(target["webSocketDebuggerUrl"], chunk))

    updated_assets = []
    for asset in assets:
        item = dict(asset)
        path = item.get("path")
        if path:
            resolved = resolved_map.get(path)
            if resolved:
                item["url"] = resolved
            if looks_unresolved(path, item.get("url")):
                fallback = fallback_url_for_path(path, res_map, base_url)
                if fallback:
                    item["url"] = fallback
        updated_assets.append(item)

    payload = {
        "version": manifest.get("version"),
        "base_url": manifest.get("base_url"),
        "assets": updated_assets,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Resolved {len(paths)} paths via page formatter")
    print(f"Wrote: {args.output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument("--target-hint")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument(
        "--resversion",
        type=Path,
        default=Path("data/resource_manifests/resversion0.11.251.w.json"),
        help="Optional raw resversion json used for fallback mappings",
    )
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
