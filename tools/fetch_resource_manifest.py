#!/usr/bin/env python3
"""Fetch Majsoul's versioned resource manifest and build a download manifest.

This script downloads:
  - version.json
  - resversion{version}.json

It can also emit a simplified downloads manifest compatible with
tools/download_asset_manifest.py.
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path
from urllib.parse import urljoin


DEFAULT_BASE_URL = "https://game.maj-soul.com/1/"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif"}
AUDIO_EXTS = {".mp3", ".ogg", ".wav", ".m4a", ".aac", ".flac"}


def fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def sanitize_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", value).strip("_") or "unknown"


def asset_kind(path: str) -> str | None:
    suffix = Path(path).suffix.lower()
    if suffix in IMAGE_EXTS:
        return "image"
    if suffix in AUDIO_EXTS:
        return "audio"
    return None


def infer_group(path: str) -> tuple[str, str]:
    parts = Path(path).parts
    if "charactor" in parts:
        idx = parts.index("charactor")
        if idx + 1 < len(parts):
            character = sanitize_name(parts[idx + 1])
            skin = sanitize_name(parts[idx + 2]) if idx + 2 < len(parts) else "default"
            return character, skin
    if "emo" in parts:
        idx = parts.index("emo")
        if idx + 1 < len(parts):
            return "emoji", sanitize_name(parts[idx + 1])
    if parts and parts[0] == "audio":
        return "audio", sanitize_name(parts[1]) if len(parts) > 1 else "default"
    if len(parts) >= 2:
        return sanitize_name(parts[0]), sanitize_name(parts[1])
    if parts:
        return sanitize_name(parts[0]), "default"
    return "ungrouped", "default"


def build_download_manifest(base_url: str, version: str, resversion: dict, include_all: bool) -> dict:
    assets = []
    resource_map = resversion.get("res", {})
    for rel_path, meta in sorted(resource_map.items()):
        kind = asset_kind(rel_path)
        if not include_all and kind is None:
            continue
        prefix = meta.get("prefix")
        if not prefix:
            continue
        character, skin = infer_group(rel_path)
        url = urljoin(base_url, f"{prefix}/{rel_path}")
        assets.append(
            {
                "character": character,
                "skin": skin,
                "type": kind or "other",
                "name": Path(rel_path).stem,
                "url": url,
                "path": rel_path,
                "prefix": prefix,
                "version": version,
            }
        )
    return {"version": version, "base_url": base_url, "assets": assets}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Majsoul base URL")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/resource_manifests"),
        help="Directory for version/resversion JSON files",
    )
    parser.add_argument(
        "--downloads-output",
        type=Path,
        default=Path("asset_preview/downloads.generated.json"),
        help="Output path for generated download manifest",
    )
    parser.add_argument(
        "--include-all",
        action="store_true",
        help="Include non-image/audio resources in generated downloads manifest",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/") + "/"
    output_dir = args.output_dir.resolve()
    downloads_output = args.downloads_output.resolve()

    version_url = urljoin(base_url, "version.json")
    version_json = fetch_json(version_url)
    version = version_json["version"]
    resversion_name = f"resversion{version}.json"
    resversion_url = urljoin(base_url, resversion_name)
    resversion_json = fetch_json(resversion_url)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "version.json").write_text(
        json.dumps(version_json, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / resversion_name).write_text(
        json.dumps(resversion_json, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    downloads_output.parent.mkdir(parents=True, exist_ok=True)
    downloads_manifest = build_download_manifest(base_url, version, resversion_json, args.include_all)
    downloads_output.write_text(
        json.dumps(downloads_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    total = len(resversion_json.get("res", {}))
    asset_total = len(downloads_manifest["assets"])
    print(f"Fetched version {version} from {base_url}")
    print(f"Wrote raw manifest: {output_dir / resversion_name}")
    print(f"Wrote download manifest: {downloads_output}")
    print(f"Resources in raw manifest: {total}")
    print(f"Assets in generated download manifest: {asset_total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
