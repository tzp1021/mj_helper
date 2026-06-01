#!/usr/bin/env python3
"""Verify asset URLs in a downloads manifest and optionally write a filtered manifest."""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import urllib.error
import urllib.request
from pathlib import Path


def check_asset(asset: dict, timeout: int) -> tuple[bool, dict]:
    url = asset.get("url", "")
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            info = {
                "status": response.status,
                "content_type": response.headers.get("Content-Type"),
                "content_length": response.headers.get("Content-Length"),
            }
            return True, info
    except Exception:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                response.read(1)
                info = {
                    "status": response.status,
                    "content_type": response.headers.get("Content-Type"),
                    "content_length": response.headers.get("Content-Length"),
                    "probe": "GET",
                }
                return True, info
        except Exception as exc:
            return False, {"error": repr(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, help="Write a filtered manifest with only passing assets")
    parser.add_argument("--report", type=Path, help="Write a JSON report")
    parser.add_argument("--limit", type=int, help="Only verify the first N assets")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--timeout", type=int, default=10)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    assets = manifest.get("assets", [])
    if args.limit:
        assets = assets[: args.limit]

    passed = []
    failed = []

    with cf.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(check_asset, asset, args.timeout): asset for asset in assets}
        for future in cf.as_completed(futures):
            asset = futures[future]
            ok, info = future.result()
            item = {"path": asset.get("path"), "url": asset.get("url"), **info}
            if ok:
                passed.append(asset)
            else:
                failed.append(item)

    passed.sort(key=lambda a: a.get("path", ""))
    failed.sort(key=lambda a: a.get("path", ""))

    if args.output:
        payload = {
            "version": manifest.get("version"),
            "base_url": manifest.get("base_url"),
            "assets": passed,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.report:
        report = {
            "input": str(args.manifest),
            "checked": len(assets),
            "passed": len(passed),
            "failed": len(failed),
            "failed_items": failed,
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"checked={len(assets)} passed={len(passed)} failed={len(failed)}")
    if args.output:
        print(f"filtered manifest -> {args.output}")
    if args.report:
        print(f"report -> {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
