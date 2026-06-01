#!/usr/bin/env python3
import argparse
import json
import shutil
from pathlib import Path


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Build a paired folder of 4-player paipu + Seer (MAKA) exports.")
    parser.add_argument("--paipu-dir", default="/Users/bigo/code/mj/paipu_exports")
    parser.add_argument("--seer-dir", default="/Users/bigo/code/mj/seer_exports")
    parser.add_argument("--output-dir", default="/Users/bigo/code/mj/tmp_paipu_4p_with_maka")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    paipu_dir = Path(args.paipu_dir)
    seer_dir = Path(args.seer_dir)
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    for child in outdir.iterdir():
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)

    seer_files = {path.name[:-10]: path for path in seer_dir.glob("*.seer.json")}
    paired = []

    for paipu_path in sorted(paipu_dir.glob("*.json"), reverse=True):
        if paipu_path.name == "record_list_summary.json":
            continue
        uuid = paipu_path.stem
        seer_path = seer_files.get(uuid)
        if not seer_path:
            continue
        paipu = load_json(paipu_path)
        seer = load_json(seer_path)
        accounts = paipu.get("accounts") or []
        actions = ((paipu.get("game_detail_records") or {}).get("actions") or [])
        events = ((((seer.get("res") or {}).get("report") or {}).get("events")) or [])
        rounds = ((((seer.get("res") or {}).get("report") or {}).get("rounds")) or [])
        if len(accounts) != 4:
            continue
        if not actions or not events:
            continue

        shutil.copy2(paipu_path, outdir / paipu_path.name)
        shutil.copy2(seer_path, outdir / seer_path.name)
        paired.append({
            "uuid": uuid,
            "paipu_file": str(outdir / paipu_path.name),
            "seer_file": str(outdir / seer_path.name),
            "action_count": len(actions),
            "seer_event_count": len(events),
            "seer_round_count": len(rounds),
            "mode_id": (((paipu.get("head") or {}).get("config") or {}).get("meta") or {}).get("mode_id"),
        })
        if len(paired) >= args.limit:
            break

    manifest = {
        "count": len(paired),
        "pairs": paired,
    }
    (outdir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[pair] pairs={len(paired)} -> {outdir}")


if __name__ == "__main__":
    main()
