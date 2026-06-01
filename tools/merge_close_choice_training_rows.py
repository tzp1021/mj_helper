#!/usr/bin/env python3
import argparse
import json
from collections import Counter
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Merge exported close-choice training row JSON files.")
    parser.add_argument("inputs", nargs="+", help="Input exported row JSON files.")
    parser.add_argument("--output", required=True, help="Merged output JSON path.")
    return parser.parse_args()


def main():
    args = parse_args()
    by_dataset = Counter()
    by_tag = Counter()
    by_mode_goal = Counter()
    rows = []
    datasets = []
    seen_datasets = set()

    for input_path in args.inputs:
        payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
        rows.extend(payload.get("rows") or [])
        for dataset in payload.get("datasets") or []:
            key = tuple(dataset)
            if key in seen_datasets:
                continue
            seen_datasets.add(key)
            datasets.append(dataset)
        by_dataset.update(payload.get("by_dataset") or {})
        by_tag.update(payload.get("by_tag") or {})
        by_mode_goal.update(payload.get("by_mode_goal") or {})

    merged = {
        "count": len(rows),
        "datasets": datasets,
        "by_dataset": dict(by_dataset.most_common()),
        "by_tag": dict(by_tag.most_common()),
        "by_mode_goal": dict(by_mode_goal.most_common()),
        "rows": rows,
    }
    out = Path(args.output)
    out.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "count": len(rows),
                "datasets": len(datasets),
                "output": str(out),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
