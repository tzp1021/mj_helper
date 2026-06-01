#!/usr/bin/env python3
import argparse
import json
from collections import Counter
from pathlib import Path


def load_jsonl(path):
    rows = []
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def key_for(row):
    return (row.get("source_file"), row.get("index"))


def compare_rows(fast_row, refined_row):
    fast_snap = fast_row.get("snapshot") or {}
    refined_snap = refined_row.get("snapshot") or {}
    fast_source_case = refined_row.get("source_case") or {}
    fast_candidates = fast_snap.get("candidates") or []
    refined_recommendation = refined_snap.get("rule_recommendation")
    candidate_tiles = [candidate.get("tile") for candidate in fast_candidates]
    candidate_rank = None
    if refined_recommendation in candidate_tiles:
        candidate_rank = candidate_tiles.index(refined_recommendation) + 1
    return {
        "source_file": refined_row.get("source_file"),
        "index": refined_row.get("index"),
        "round": refined_snap.get("round") or fast_snap.get("round"),
        "trigger": refined_snap.get("trigger") or fast_snap.get("trigger"),
        "priority_score": fast_source_case.get("priority_score"),
        "priority_tags": fast_source_case.get("priority_tags") or [],
        "fast_recommendation": fast_snap.get("rule_recommendation"),
        "fast_recommendation_display": fast_snap.get("rule_recommendation_display"),
        "refined_recommendation": refined_recommendation,
        "refined_recommendation_display": refined_snap.get("rule_recommendation_display"),
        "same_recommendation": fast_snap.get("rule_recommendation") == refined_snap.get("rule_recommendation"),
        "candidate_count": len(fast_candidates),
        "refined_candidate_rank": candidate_rank,
        "candidate_missing": bool(refined_recommendation and candidate_rank is None),
        "fast_confidence": fast_snap.get("confidence"),
        "refined_confidence": refined_snap.get("confidence"),
        "fast_push_fold": fast_snap.get("push_fold"),
        "refined_push_fold": refined_snap.get("push_fold"),
        "fast_hand_goal": fast_snap.get("hand_goal"),
        "refined_hand_goal": refined_snap.get("hand_goal"),
    }


def main():
    parser = argparse.ArgumentParser(description="Compare fast-pass replay rows against refined rerun rows.")
    parser.add_argument("fast_jsonl")
    parser.add_argument("refined_jsonl")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    fast_rows = {key_for(row): row for row in load_jsonl(args.fast_jsonl)}
    refined_rows = load_jsonl(args.refined_jsonl)
    compared = []
    change_counter = Counter()
    for row in refined_rows:
        key = key_for(row)
        fast_row = fast_rows.get(key)
        if not fast_row:
            continue
        item = compare_rows(fast_row, row)
        compared.append(item)
        if item["same_recommendation"]:
            change_counter["same_recommendation"] += 1
        else:
            change_counter["changed_recommendation"] += 1
        if item["fast_push_fold"] != item["refined_push_fold"]:
            change_counter["changed_push_fold"] += 1
        if item["fast_hand_goal"] != item["refined_hand_goal"]:
            change_counter["changed_hand_goal"] += 1
        if item["candidate_missing"]:
            change_counter["candidate_missing"] += 1
        elif item["refined_candidate_rank"]:
            change_counter[f"refined_candidate_rank_{item['refined_candidate_rank']}"] += 1

    payload = {
        "count": len(compared),
        "change_counts": dict(change_counter.most_common()),
        "rows": compared,
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "count": len(compared),
        "change_counts": dict(change_counter.most_common()),
        "output": args.output,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
