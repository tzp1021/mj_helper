#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from train_close_choice_model import train_averaged_perceptron


def parse_args():
    parser = argparse.ArgumentParser(description="Train close-choice evaluator from exported training rows.")
    parser.add_argument("rows_json", help="Merged close-choice training rows JSON.")
    parser.add_argument(
        "--output",
        default="/Users/bigo/code/mj/data/archive/close_choice_model.json",
        help="Output JSON path for learned weights.",
    )
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def build_examples_from_rows(rows):
    examples = []
    for row in rows:
        diff = row.get("feature_diff") or {}
        weight = max(1, int(row.get("row_weight", 1) or 1))
        for _ in range(weight):
            examples.append((diff, 1))
            examples.append(({key: -value for key, value in diff.items()}, -1))
    return examples


def count_mode_goal(rows):
    counts = {}
    for row in rows:
        key = f'{row.get("push_fold")}/{row.get("hand_goal")}'
        counts[key] = counts.get(key, 0) + int(row.get("row_weight", 1) or 1)
    return counts


def main():
    args = parse_args()
    payload = json.loads(Path(args.rows_json).read_text(encoding="utf-8"))
    rows = payload.get("rows") or []
    if not rows:
        raise SystemExit("No rows found in rows_json.")
    examples = build_examples_from_rows(rows)
    weights, bias, train_acc, val_acc = train_averaged_perceptron(examples, args.epochs, args.seed)
    model_payload = {
        "version": 1,
        "scope": "all_last_close_choice",
        "rows_json": args.rows_json,
        "datasets": payload.get("datasets") or [],
        "bias": bias,
        "weights": weights,
        "training": {
            "rows": len(rows),
            "eligible_rows": len(rows),
            "pairwise_examples": len(examples),
            "weighted_rows": sum(int(row.get("row_weight", 1) or 1) for row in rows),
            "epochs": args.epochs,
            "seed": args.seed,
            "train_accuracy": train_acc,
            "validation_accuracy": val_acc,
            "by_dataset": payload.get("by_dataset") or {},
            "by_tag": payload.get("by_tag") or {},
            "by_mode_goal": count_mode_goal(rows),
        },
    }
    out = Path(args.output)
    out.write_text(json.dumps(model_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(out),
                **model_payload["training"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
