#!/usr/bin/env python3
import argparse
import json
from collections import Counter
from pathlib import Path


NEW_DATASET_PREFIXES = (
    "tenhou_mjlog4_refine_compare",
    "tenhou_mjlog5_refine_compare",
    "tenhou_mjlog6_refine_compare",
)


def parse_args():
    parser = argparse.ArgumentParser(description="Apply heuristic row weights to close-choice training rows.")
    parser.add_argument("rows_json")
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--preset",
        default="stable_old_plus_cautious_new",
        choices=["stable_old_plus_cautious_new"],
    )
    return parser.parse_args()


def is_new_dataset(dataset):
    return dataset.startswith(NEW_DATASET_PREFIXES)


def choose_weight(row):
    dataset = row.get("dataset") or ""
    mode = row.get("push_fold")
    goal = row.get("hand_goal")
    tags = set(row.get("priority_tags") or [])

    if not is_new_dataset(dataset):
        return 3, "old_dataset_boost"

    if mode == "neutral" and goal == "稳定优先" and "very_close" in tags:
        return 1, "new_neutral_stability_very_close_downweight"
    if mode == "fold" and goal == "稳定优先":
        return 1, "new_fold_stability_downweight"
    if mode == "neutral" and goal == "打点优先":
        return 1, "new_neutral_value_downweight"
    if mode == "push" and goal == "打点优先" and "very_close" in tags:
        return 2, "new_push_value_keep"
    return 2, "new_default_midweight"


def main():
    args = parse_args()
    payload = json.loads(Path(args.rows_json).read_text(encoding="utf-8"))
    rows = payload.get("rows") or []

    weighted_rows = []
    by_reason = Counter()
    by_dataset_weight = Counter()
    weighted_count = 0

    for row in rows:
        new_row = dict(row)
        weight, reason = choose_weight(row)
        new_row["row_weight"] = weight
        new_row["weight_reason"] = reason
        weighted_rows.append(new_row)
        by_reason[reason] += 1
        by_dataset_weight[row["dataset"]] += weight
        weighted_count += weight

    out_payload = {
        **payload,
        "preset": args.preset,
        "weighted_count": weighted_count,
        "weight_reason_counts": dict(by_reason.most_common()),
        "dataset_weight_totals": dict(by_dataset_weight.most_common()),
        "rows": weighted_rows,
    }
    out = Path(args.output)
    out.write_text(json.dumps(out_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "rows": len(weighted_rows),
                "weighted_count": weighted_count,
                "weight_reason_counts": dict(by_reason.most_common()),
                "output": str(out),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
