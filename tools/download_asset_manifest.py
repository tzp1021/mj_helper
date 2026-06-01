#!/usr/bin/env python3
"""Download assets from an explicit user-provided manifest.

This is intentionally generic: it downloads URLs listed in a manifest you
provide and writes them under --output-dir. It does not discover, scrape, or
derive game asset endpoints.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


def safe_destination(output_dir: Path, rel_path: str) -> Path:
    if not rel_path:
        raise ValueError("asset path is empty")
    rel = Path(rel_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"unsafe relative path: {rel_path}")
    dest = (output_dir / rel).resolve()
    if output_dir.resolve() not in dest.parents and dest != output_dir.resolve():
        raise ValueError(f"path escapes output dir: {rel_path}")
    return dest


def infer_path(asset: dict) -> str:
    if asset.get("path"):
        return str(asset["path"])
    parsed = urlparse(str(asset.get("url", "")))
    name = Path(parsed.path).name
    if not name:
        raise ValueError("missing path and URL filename")
    character = str(asset.get("character") or "ungrouped").strip().replace("/", "_")
    skin = str(asset.get("skin") or "default").strip().replace("/", "_")
    return f"{character}/{skin}/{name}"


def download(url: str, dest: Path, timeout: int, overwrite: bool) -> str:
    if dest.exists() and not overwrite:
        return "skipped"
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "local-asset-previewer/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        with dest.open("wb") as file:
            shutil.copyfileobj(response, file)
    return "downloaded"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="JSON manifest with an assets array")
    parser.add_argument("--output-dir", type=Path, default=Path("data/majsoul_assets"))
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    output_dir = args.output_dir.resolve()
    assets = manifest.get("assets", [])

    ok = 0
    failed = 0
    for index, asset in enumerate(assets, start=1):
        url = str(asset.get("url") or "").strip()
        if not url:
            print(f"[{index}] missing url", file=sys.stderr)
            failed += 1
            continue
        try:
            dest = safe_destination(output_dir, infer_path(asset))
            status = download(url, dest, args.timeout, args.overwrite)
            print(f"[{index}] {status}: {dest}")
            ok += 1
        except (OSError, ValueError, urllib.error.URLError) as exc:
            print(f"[{index}] failed: {url} ({exc})", file=sys.stderr)
            failed += 1

    print(f"Done. ok={ok} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

