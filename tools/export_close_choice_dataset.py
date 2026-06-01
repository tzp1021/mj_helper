#!/usr/bin/env python3
import argparse
import json
from collections import Counter
from pathlib import Path

from close_choice_data import DEFAULT_DATASETS, iter_eligible_rows


def parse_args():
    parser = argparse.ArgumentParser(description="Export eligible close-choice training rows.")
    parser.add_argument(
        "--dataset",
        action="append",
        nargs=2,
        metavar=("FAST_JSONL", "COMPARE_JSON"),
        help="Pair of fast replay JSONL and fast-vs-refined compare JSON.",
    )
    parser.add_argument(
        "--output",
        default="/Users/bigo/code/mj/data/archive/close_choice_training_rows.json",
        help="Output JSON path.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    datasets = args.dataset or DEFAULT_DATASETS
    rows = list(iter_eligible_rows(datasets))
    by_dataset = Counter()
    by_tag = Counter()
    by_mode_goal = Counter()
    for row in rows:
        by_dataset[row["dataset"]] += 1
        by_tag.update(row.get("priority_tags") or [])
        by_mode_goal[(row["push_fold"], row["hand_goal"])] += 1
    payload = {
        "count": len(rows),
        "datasets": datasets,
        "by_dataset": dict(by_dataset.most_common()),
        "by_tag": dict(by_tag.most_common()),
        "by_mode_goal": {
            f"{mode}/{goal}": count for (mode, goal), count in by_mode_goal.most_common()
        },
        "rows": rows,
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "count": len(rows),
        "by_dataset": dict(by_dataset.most_common()),
        "output": args.output,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
