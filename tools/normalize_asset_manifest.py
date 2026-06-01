#!/usr/bin/env python3
"""Normalize a local asset manifest for preview by making group/name tuples unique."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def suffix_from_path(path: str) -> str:
    rel = Path(path)
    parts = rel.parts
    if len(parts) >= 3:
        return " / ".join(parts[-3:-1])
    if len(parts) >= 2:
        return " / ".join(parts[-2:-1])
    return rel.stem


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    assets = manifest.get("assets", [])

    key_counts = Counter((a.get("character"), a.get("skin"), a.get("name")) for a in assets)
    seen = defaultdict(int)

    normalized = []
    for asset in assets:
        item = dict(asset)
        key = (item.get("character"), item.get("skin"), item.get("name"))
        if key_counts[key] > 1:
            seen[key] += 1
            suffix = suffix_from_path(item.get("path", ""))
            item["name"] = f"{item.get('name')} [{suffix}]"
            if seen[key] > 1:
                item["name"] = f"{item['name']} #{seen[key]}"
        normalized.append(item)

    payload = {**manifest, "assets": normalized}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote normalized manifest: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
