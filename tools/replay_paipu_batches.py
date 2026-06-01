#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from majsoul_live_helper import clear_replay_caches, parse_paipu_actions


def load_manifest(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload.get("files") or []


def main():
    parser = argparse.ArgumentParser(description="Replay paipu manifest in batches with append-only snapshots.")
    parser.add_argument("file_manifest", help="Manifest JSON with top-level 'files'.")
    parser.add_argument("--player-name", default="Levey")
    parser.add_argument("--snapshot-jsonl", required=True)
    parser.add_argument("--summary-json", required=True)
    parser.add_argument("--lookahead-limit", type=int, default=0)
    parser.add_argument("--include-aux-advice", action="store_true")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--append", action="store_true", help="Append snapshots instead of overwriting.")
    args = parser.parse_args()

    rows = load_manifest(args.file_manifest)
    if args.start:
        rows = rows[args.start:]
    if args.limit is not None:
        rows = rows[:args.limit]

    target = Path(args.snapshot_jsonl)
    target.parent.mkdir(parents=True, exist_ok=True)
    summary_rows = []
    total_suggestions = 0

    mode = "a" if args.append else "w"
    with target.open(mode, encoding="utf-8") as fh:
        for offset, row in enumerate(rows, start=args.start):
            path = row.get("file")
            if not path:
                continue
            decoded_count, outputs = parse_paipu_actions(
                path,
                player_name=args.player_name,
                lookahead_limit=args.lookahead_limit,
                include_aux_advice=args.include_aux_advice,
            )
            for item in outputs:
                payload = {
                    "index": item["index"],
                    "suggestion": item["suggestion"],
                    "snapshot": item.get("snapshot"),
                    "action_plan": item.get("action_plan"),
                    "tenpai_analysis": item.get("tenpai_analysis"),
                    "source_file": path,
                }
                fh.write(json.dumps(payload, ensure_ascii=False))
                fh.write("\n")
            total_suggestions += len(outputs)
            summary_rows.append({
                "offset": offset,
                "uuid": row.get("uuid"),
                "file": path,
                "decoded_records": decoded_count,
                "suggestions": len(outputs),
            })
            clear_replay_caches()
            print(
                f"[batch-replay] {offset + 1}/{args.start + len(rows)} {Path(path).name}: "
                f"records={decoded_count} suggestions={len(outputs)}",
                flush=True,
            )

    summary = {
        "files": len(summary_rows),
        "start": args.start,
        "limit": args.limit,
        "lookahead_limit": args.lookahead_limit,
        "include_aux_advice": args.include_aux_advice,
        "total_suggestions": total_suggestions,
        "rows": summary_rows,
    }
    Path(args.summary_json).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[batch-replay] snapshots: {target}")
    print(f"[batch-replay] summary: {args.summary_json}")
    print(f"[batch-replay] total suggestions: {total_suggestions}")


if __name__ == "__main__":
    main()
