#!/usr/bin/env python3
"""Slice a generated Majsoul download manifest into smaller category manifests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


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


def select_assets(assets: list[dict], category: str) -> list[dict]:
    if category == "maka":
        return [a for a in assets if "maka" in a["path"].lower()]
    if category == "characters":
        return [a for a in assets if "charactor" in a["path"].lower()]
    if category == "voices":
        return [a for a in assets if a["path"].startswith("audio/sound/")]
    if category == "lobby_audio":
        return [a for a in assets if a["path"].startswith("audio/audio_lobby/")]
    if category == "emoji":
        return [a for a in assets if "/emo/" in a["path"]]
    raise ValueError(f"unknown category: {category}")


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
        help="Directory to write sliced manifests",
    )
    parser.add_argument(
        "--categories",
        nargs="+",
        default=["maka", "characters", "voices", "lobby_audio", "emoji"],
        help="Categories to emit",
    )
    args = parser.parse_args()

    base = load_manifest(args.manifest)
    assets = base.get("assets", [])
    for category in args.categories:
        selected = select_assets(assets, category)
        out = args.output_dir / f"downloads.{category}.json"
        dump_manifest(out, base, selected)
        print(f"{category}: {len(selected)} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
