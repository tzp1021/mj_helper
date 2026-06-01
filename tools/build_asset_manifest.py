#!/usr/bin/env python3
"""Build a local asset manifest for asset_preview/.

The script only scans files already present on disk. It does not contact game
services or infer remote asset URLs.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif"}
AUDIO_EXTS = {".mp3", ".ogg", ".wav", ".m4a", ".aac", ".flac"}


def guess_type(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in AUDIO_EXTS:
        return "audio"
    return None


def guess_group(root: Path, path: Path) -> tuple[str, str]:
    rel = path.relative_to(root)
    parts = rel.parts
    if "charactor" in parts:
        idx = parts.index("charactor")
        if idx + 1 < len(parts):
            character = parts[idx + 1]
            skin = parts[idx + 2] if idx + 2 < len(parts) and parts[idx + 2] != path.name else "默认"
            return character, skin
    if "emo" in parts:
        idx = parts.index("emo")
        if idx + 1 < len(parts):
            return "emoji", parts[idx + 1]
    if parts[:2] == ("audio", "sound"):
        if len(parts) >= 3:
            return parts[2], "voice"
        return "audio", "voice"
    if parts and parts[0] == "audio":
        return "audio", parts[1] if len(parts) >= 2 else "默认"
    character = parts[0] if len(parts) >= 2 else "未分组"
    skin = parts[1] if len(parts) >= 3 else "默认"
    return character, skin


def build_manifest(asset_dir: Path, preview_dir: Path) -> dict:
    assets = []
    for path in sorted(asset_dir.rglob("*")):
        if not path.is_file():
            continue
        asset_type = guess_type(path)
        if not asset_type:
            continue
        character, skin = guess_group(asset_dir, path)
        rel_to_preview = os.path.relpath(path.resolve(), preview_dir.resolve())
        assets.append(
            {
                "character": character,
                "skin": skin,
                "type": asset_type,
                "name": path.stem.replace("_", " "),
                "path": Path(rel_to_preview).as_posix(),
            }
        )
    return {"assets": assets}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asset_dir", type=Path, help="Directory containing local assets")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("asset_preview/manifest.json"),
        help="Manifest path for the previewer",
    )
    args = parser.parse_args()

    asset_dir = args.asset_dir.resolve()
    output = args.output.resolve()
    if not asset_dir.is_dir():
        parser.error(f"asset_dir is not a directory: {asset_dir}")

    manifest = build_manifest(asset_dir, output.parent)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(manifest['assets'])} assets to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
