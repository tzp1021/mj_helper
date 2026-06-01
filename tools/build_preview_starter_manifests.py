#!/usr/bin/env python3
"""Build smaller, practical asset manifests for local preview."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


PORTRAIT_FILES = {"full.png", "half.png", "smallhead.png", "bighead.png", "waitingroom.png"}


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_manifest(path: Path, base: dict, assets: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": base.get("version"),
        "base_url": base.get("base_url"),
        "assets": assets,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def portrait_priority(folder_name: str) -> tuple[int, int, str]:
    # Prefer the base/default skin, then `_0`, then other suffixed variants.
    if folder_name.endswith("_0"):
        return (1, len(folder_name), folder_name)
    if "_" not in folder_name:
        return (0, len(folder_name), folder_name)
    return (2, len(folder_name), folder_name)


def group_default_portraits(assets: list[dict]) -> list[dict]:
    buckets: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for asset in assets:
        path = asset["path"]
        parts = Path(path).parts
        if len(parts) < 4:
            continue
        if parts[0] != "chs_t":
            continue
        if "charactor" not in parts:
            continue
        if Path(path).name not in PORTRAIT_FILES:
            continue
        idx = parts.index("charactor")
        if idx + 1 >= len(parts):
            continue
        folder = parts[idx + 1]
        base_name = folder[:-2] if folder.endswith("_0") else folder.split("_", 1)[0]
        buckets[base_name][folder].append(asset)

    selected: list[dict] = []
    for _base_name, folder_map in sorted(buckets.items()):
        chosen_folder = min(folder_map.keys(), key=portrait_priority)
        chosen_assets = sorted(folder_map[chosen_folder], key=lambda a: a["path"])
        selected.extend(chosen_assets)
    return selected


def build_starter(default_portraits: list[dict], all_assets: list[dict]) -> list[dict]:
    maka_assets = [asset for asset in all_assets if "maka" in asset["path"].lower()]
    seen = set()
    merged = []
    for asset in maka_assets + default_portraits:
        key = asset["path"]
        if key in seen:
            continue
        seen.add(key)
        merged.append(asset)
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "manifest",
        type=Path,
        nargs="?",
        default=Path("asset_preview/downloads.generated.json"),
        help="Input downloads manifest",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("asset_preview/slices"),
        help="Directory to write starter manifests",
    )
    args = parser.parse_args()

    base = load_manifest(args.manifest)
    assets = base.get("assets", [])
    default_portraits = group_default_portraits(assets)
    starter = build_starter(default_portraits, assets)

    portraits_out = args.output_dir / "downloads.default_portraits.json"
    starter_out = args.output_dir / "downloads.starter.json"
    dump_manifest(portraits_out, base, default_portraits)
    dump_manifest(starter_out, base, starter)

    print(f"default_portraits: {len(default_portraits)} -> {portraits_out}")
    print(f"starter: {len(starter)} -> {starter_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
