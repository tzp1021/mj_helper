#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from majsoul_live_helper import parse_paipu_actions


def main():
    parser = argparse.ArgumentParser(description="Replay Majsoul paipu JSON files into decision snapshots.")
    parser.add_argument("paipu_dir", help="Directory containing exported fetchGameRecord JSON files")
    parser.add_argument("--player-name", default="Levey", help="Target player nickname to analyze")
    parser.add_argument("--manifest", help="Optional manifest.json path")
    parser.add_argument("--snapshot-jsonl", required=True, help="Output snapshot jsonl path")
    args = parser.parse_args()

    root = Path(args.paipu_dir)
    files = sorted(p for p in root.glob("*.json") if p.name != "manifest.json")
    rows = []
    summary = []
    for path in files:
        decoded_count, outputs = parse_paipu_actions(
            str(path),
            player_name=args.player_name,
            manifest_path=args.manifest,
        )
        summary.append({
            "file": str(path),
            "decoded_records": decoded_count,
            "suggestions": len(outputs),
        })
        rows.extend(outputs)
        print(f"[replay] {path.name}: records={decoded_count} suggestions={len(outputs)}")

    target = Path(args.snapshot_jsonl)
    lines = []
    for item in rows:
        payload = {
            "index": item["index"],
            "suggestion": item["suggestion"],
            "snapshot": item.get("snapshot"),
            "action_plan": item.get("action_plan"),
            "tenpai_analysis": item.get("tenpai_analysis"),
        }
        lines.append(json.dumps(payload, ensure_ascii=False))
    target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    print(f"[replay] snapshots: {target}")
    print(f"[replay] total suggestions: {len(rows)}")


if __name__ == "__main__":
    main()
