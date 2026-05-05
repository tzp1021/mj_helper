#!/usr/bin/env python3
import argparse
import json
import shutil
from pathlib import Path


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(
        description="Build a lightweight folder of 4-player paipu + Seer data for offline analysis."
    )
    parser.add_argument("--source-dir", default="/Users/bigo/code/mj/tmp_paipu_4p_with_maka")
    parser.add_argument("--output-dir", default="/Users/bigo/code/mj/tmp_paipu_4p_with_maka_light")
    args = parser.parse_args()

    source_dir = Path(args.source_dir)
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    for child in outdir.iterdir():
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)

    manifest = load_json(source_dir / "manifest.json")
    pairs = []

    for pair in manifest.get("pairs") or []:
        uuid = pair["uuid"]
        paipu = load_json(source_dir / f"{uuid}.json")
        seer = load_json(source_dir / f"{uuid}.seer.json")

        payload = {
            "uuid": uuid,
            "meta": {
                "mode_id": pair.get("mode_id"),
                "action_count": pair.get("action_count"),
                "seer_event_count": pair.get("seer_event_count"),
                "seer_round_count": pair.get("seer_round_count"),
            },
            "head": paipu.get("head"),
            "accounts": paipu.get("accounts"),
            "result": paipu.get("result"),
            "actions": ((paipu.get("game_detail_records") or {}).get("actions") or []),
            "seer_report": ((seer.get("res") or {}).get("report") or {}),
        }

        target = outdir / f"{uuid}.analysis.json"
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        pairs.append({
            "uuid": uuid,
            "file": str(target),
            "action_count": pair.get("action_count"),
            "seer_event_count": pair.get("seer_event_count"),
            "seer_round_count": pair.get("seer_round_count"),
        })

    (outdir / "manifest.json").write_text(
        json.dumps({"count": len(pairs), "pairs": pairs}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[light] files={len(pairs)} -> {outdir}")


if __name__ == "__main__":
    main()
