#!/usr/bin/env python3
"""Validate and summarize a local asset preview manifest."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse


VALID_TYPES = {"image", "audio"}


def is_remote(path: str) -> bool:
    scheme = urlparse(path).scheme
    return scheme in {"http", "https", "data"}


def validate(manifest_path: Path, check_files: bool) -> tuple[list[str], dict]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assets = manifest.get("assets")
    errors: list[str] = []
    if not isinstance(assets, list):
        return ["manifest.assets must be an array"], {}

    type_counts: Counter[str] = Counter()
    character_counts: Counter[str] = Counter()
    skin_counts: dict[str, Counter[str]] = defaultdict(Counter)
    seen_ids: set[str] = set()
    base_dir = manifest_path.parent

    for index, asset in enumerate(assets):
        label = f"assets[{index}]"
        if not isinstance(asset, dict):
            errors.append(f"{label} must be an object")
            continue

        asset_type = str(asset.get("type") or "")
        path = str(asset.get("path") or "")
        character = str(asset.get("character") or "未分组")
        skin = str(asset.get("skin") or "默认")
        asset_id = str(asset.get("id") or f"{character}/{skin}/{asset.get('name') or path}")

        if asset_type not in VALID_TYPES:
            errors.append(f"{label}.type must be one of {sorted(VALID_TYPES)}")
        if not path:
            errors.append(f"{label}.path is required")
        if asset_id in seen_ids:
            errors.append(f"{label} duplicates id/name/path group: {asset_id}")
        seen_ids.add(asset_id)

        if check_files and path and not is_remote(path):
            local_path = (base_dir / path).resolve()
            if not local_path.exists():
                errors.append(f"{label}.path does not exist: {path}")

        type_counts[asset_type] += 1
        character_counts[character] += 1
        skin_counts[character][skin] += 1

    summary = {
        "assets": len(assets),
        "types": dict(type_counts),
        "characters": len(character_counts),
        "top_characters": character_counts.most_common(10),
        "skins_by_character": {name: len(skins) for name, skins in sorted(skin_counts.items())},
    }
    return errors, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="asset_preview manifest.json")
    parser.add_argument("--check-files", action="store_true", help="Ensure local paths exist")
    parser.add_argument("--json", action="store_true", help="Print JSON summary")
    args = parser.parse_args()

    try:
        errors, summary = validate(args.manifest, args.check_files)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"failed to read manifest: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"ok": not errors, "errors": errors, "summary": summary}, ensure_ascii=False, indent=2))
    else:
        print(f"assets: {summary.get('assets', 0)}")
        print(f"characters: {summary.get('characters', 0)}")
        print(f"types: {summary.get('types', {})}")
        for character, count in summary.get("top_characters", []):
            print(f"- {character}: {count}")
        if errors:
            print("\nErrors:", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
