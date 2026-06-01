#!/usr/bin/env python3
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from majsoul_live_helper import clear_replay_caches, parse_paipu_actions


def load_cases(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload.get("cases") or []


def group_cases_by_source(cases):
    grouped = defaultdict(list)
    for case in cases:
        source = case.get("source_file")
        index = case.get("index")
        if not source or index is None:
            continue
        grouped[source].append(case)
    for source in grouped:
        grouped[source].sort(key=lambda item: item["index"])
    return grouped


def build_case_lookup(cases):
    lookup = {}
    for case in cases:
        source = case.get("source_file")
        index = case.get("index")
        if source and index is not None:
            lookup[(source, index)] = case
    return lookup


def load_completed_keys(path):
    out_path = Path(path)
    if not out_path.exists():
        return set()
    completed = set()
    with out_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            source = payload.get("source_file")
            index = payload.get("index")
            if source and index is not None:
                completed.add((source, index))
    return completed


def main():
    parser = argparse.ArgumentParser(description="Rerun selected high-value replay cases with deeper lookahead.")
    parser.add_argument("cases_json")
    parser.add_argument("--player-name", default="Levey")
    parser.add_argument("--lookahead-limit", type=int, default=2)
    parser.add_argument("--include-aux-advice", action="store_true")
    parser.add_argument("--snapshot-jsonl", required=True)
    parser.add_argument("--summary-json", required=True)
    parser.add_argument("--start", type=int, default=0, help="Optional starting case offset within the input list.")
    parser.add_argument("--limit", type=int, help="Optional cap on number of cases from the input list.")
    parser.add_argument("--append", action="store_true", help="Append to an existing snapshot file instead of overwriting.")
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="When appending, skip cases already present in the existing snapshot JSONL.",
    )
    args = parser.parse_args()

    all_cases = load_cases(args.cases_json)
    if args.start:
        all_cases = all_cases[args.start:]
    if args.limit is not None:
        all_cases = all_cases[: args.limit]
    grouped = group_cases_by_source(all_cases)
    case_lookup = build_case_lookup(all_cases)

    out_path = Path(args.snapshot_jsonl)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    completed_keys = load_completed_keys(out_path) if args.append and args.skip_existing else set()
    total_outputs = 0
    summary_rows = []

    file_mode = "a" if args.append else "w"
    with out_path.open(file_mode, encoding="utf-8") as fh:
        for source, cases in grouped.items():
            indices = [
                case["index"]
                for case in cases
                if (source, case["index"]) not in completed_keys
            ]
            if not indices:
                summary_rows.append({
                    "source_file": source,
                    "requested_indices": [],
                    "max_index": None,
                    "decoded_records": 0,
                    "matched_outputs": 0,
                    "skipped_existing": len(cases),
                })
                print(
                    f"[refine-rerun] {Path(source).name}: skipped existing {len(cases)}",
                    flush=True,
                )
                continue
            max_index = max(indices)
            decoded_count, outputs = parse_paipu_actions(
                source,
                player_name=args.player_name,
                target_indices=indices,
                max_index=max_index,
                lookahead_limit=args.lookahead_limit,
                include_aux_advice=args.include_aux_advice,
            )
            emitted = 0
            for row in outputs:
                key = (source, row.get("index"))
                source_case = case_lookup.get(key) or {}
                payload = {
                    "index": row["index"],
                    "suggestion": row.get("suggestion"),
                    "snapshot": row.get("snapshot"),
                    "action_plan": row.get("action_plan"),
                    "tenpai_analysis": row.get("tenpai_analysis"),
                    "source_file": source,
                    "source_case": {
                        "priority_score": source_case.get("priority_score"),
                        "priority_tags": source_case.get("priority_tags"),
                        "confidence": source_case.get("confidence"),
                        "rule_recommendation": source_case.get("rule_recommendation"),
                        "rule_recommendation_display": source_case.get("rule_recommendation_display"),
                    },
                }
                fh.write(json.dumps(payload, ensure_ascii=False))
                fh.write("\n")
                emitted += 1
            total_outputs += emitted
            summary_rows.append({
                "source_file": source,
                "requested_indices": indices,
                "max_index": max_index,
                "decoded_records": decoded_count,
                "matched_outputs": emitted,
                "skipped_existing": len(cases) - len(indices),
            })
            clear_replay_caches()
            print(
                f"[refine-rerun] {Path(source).name}: requested={len(indices)} matched={emitted} decoded={decoded_count}",
                flush=True,
            )

    summary = {
        "cases_requested": len(all_cases),
        "files": len(summary_rows),
        "lookahead_limit": args.lookahead_limit,
        "include_aux_advice": args.include_aux_advice,
        "matched_outputs": total_outputs,
        "rows": summary_rows,
    }
    Path(args.summary_json).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[refine-rerun] snapshots: {args.snapshot_jsonl}")
    print(f"[refine-rerun] summary: {args.summary_json}")
    print(f"[refine-rerun] matched outputs: {total_outputs}")


if __name__ == "__main__":
    main()
