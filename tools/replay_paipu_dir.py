#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from majsoul_live_helper import clear_replay_caches, parse_paipu_actions


def main():
    parser = argparse.ArgumentParser(description="Replay Majsoul/Tenhou replay files into decision snapshots.")
    parser.add_argument("paipu_dir", help="Directory containing exported replay files")
    parser.add_argument("--player-name", default="Levey", help="Target player nickname to analyze")
    parser.add_argument("--manifest", help="Optional manifest.json path")
    parser.add_argument("--file-manifest", help="Optional JSON manifest with a top-level 'files' list.")
    parser.add_argument("--start", type=int, default=0, help="Start offset in the selected file list.")
    parser.add_argument("--limit", type=int, help="Optional max number of files to replay.")
    parser.add_argument("--append", action="store_true", help="Append to snapshot jsonl instead of overwriting.")
    parser.add_argument("--lookahead-limit", type=int, default=0, help="How many same-shanten candidates use deep future-progress lookahead.")
    parser.add_argument("--include-aux-advice", action="store_true", help="Include tenpai/riichi auxiliary advice in replay output.")
    parser.add_argument("--snapshot-jsonl", required=True, help="Output snapshot jsonl path")
    args = parser.parse_args()

    root = Path(args.paipu_dir)
    if args.file_manifest:
        manifest_payload = json.loads(Path(args.file_manifest).read_text(encoding="utf-8"))
        rows = manifest_payload.get("files") or []
        files = [Path(item["file"]) for item in rows if item.get("file")]
    else:
        files = sorted(
            p for pattern in ("*.json", "*.mjlog") for p in root.glob(pattern)
            if (
                p.suffix == ".mjlog"
                or (
                    p.name not in {"manifest.json", "record_list_summary.json"}
                    and not p.name.startswith("manifest_")
                )
            )
        )
    if args.start:
        files = files[args.start:]
    if args.limit is not None:
        files = files[:args.limit]
    summary = []
    target = Path(args.snapshot_jsonl)
    total_suggestions = 0
    mode = "a" if args.append else "w"
    with target.open(mode, encoding="utf-8") as fh:
        for path in files:
            decoded_count, outputs = parse_paipu_actions(
                str(path),
                player_name=args.player_name,
                manifest_path=args.manifest,
                lookahead_limit=args.lookahead_limit,
                include_aux_advice=args.include_aux_advice,
            )
            summary.append({
                "file": str(path),
                "decoded_records": decoded_count,
                "suggestions": len(outputs),
            })
            total_suggestions += len(outputs)
            for item in outputs:
                payload = {
                    "index": item["index"],
                    "suggestion": item["suggestion"],
                    "snapshot": item.get("snapshot"),
                    "action_plan": item.get("action_plan"),
                    "tenpai_analysis": item.get("tenpai_analysis"),
                }
                fh.write(json.dumps(payload, ensure_ascii=False))
                fh.write("\n")
            clear_replay_caches()
            print(f"[replay] {path.name}: records={decoded_count} suggestions={len(outputs)}")
    print(f"[replay] snapshots: {target}")
    print(f"[replay] total suggestions: {total_suggestions}")


if __name__ == "__main__":
    main()
