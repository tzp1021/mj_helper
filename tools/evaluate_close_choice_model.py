#!/usr/bin/env python3
import argparse
import json
from collections import Counter
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate close-choice model against a no-model baseline.")
    parser.add_argument("model_compare_json")
    parser.add_argument("baseline_compare_json")
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    model_rows = json.loads(Path(args.model_compare_json).read_text(encoding="utf-8")).get("rows") or []
    base_rows = json.loads(Path(args.baseline_compare_json).read_text(encoding="utf-8")).get("rows") or []
    model_map = {(row["source_file"], row["index"]): row for row in model_rows}
    base_map = {(row["source_file"], row["index"]): row for row in base_rows}

    fixed_by_model = []
    worsened_by_model = []
    both_same = 0
    both_diff = 0
    fixed_tags = Counter()
    worsened_tags = Counter()
    fixed_mode_goal = Counter()
    worsened_mode_goal = Counter()

    for key in sorted(set(model_map) & set(base_map)):
        model_row = model_map[key]
        base_row = base_map[key]
        model_same = bool(model_row.get("same_recommendation"))
        base_same = bool(base_row.get("same_recommendation"))
        if model_same and not base_same:
            fixed_by_model.append({
                "source_file": key[0],
                "index": key[1],
                "baseline_fast": base_row.get("fast_recommendation"),
                "model_fast": model_row.get("fast_recommendation"),
                "refined": model_row.get("refined_recommendation"),
                "priority_tags": model_row.get("priority_tags") or [],
                "push_fold": model_row.get("fast_push_fold"),
                "hand_goal": model_row.get("fast_hand_goal"),
            })
            fixed_tags.update(model_row.get("priority_tags") or [])
            fixed_mode_goal[(model_row.get("fast_push_fold"), model_row.get("fast_hand_goal"))] += 1
        elif base_same and not model_same:
            worsened_by_model.append({
                "source_file": key[0],
                "index": key[1],
                "baseline_fast": base_row.get("fast_recommendation"),
                "model_fast": model_row.get("fast_recommendation"),
                "refined": model_row.get("refined_recommendation"),
                "priority_tags": model_row.get("priority_tags") or [],
                "push_fold": model_row.get("fast_push_fold"),
                "hand_goal": model_row.get("fast_hand_goal"),
            })
            worsened_tags.update(model_row.get("priority_tags") or [])
            worsened_mode_goal[(model_row.get("fast_push_fold"), model_row.get("fast_hand_goal"))] += 1
        elif model_same and base_same:
            both_same += 1
        else:
            both_diff += 1

    payload = {
        "count": len(set(model_map) & set(base_map)),
        "model_same": sum(1 for row in model_rows if row.get("same_recommendation")),
        "baseline_same": sum(1 for row in base_rows if row.get("same_recommendation")),
        "fixed_by_model": len(fixed_by_model),
        "worsened_by_model": len(worsened_by_model),
        "net_gain": len(fixed_by_model) - len(worsened_by_model),
        "both_same": both_same,
        "both_diff": both_diff,
        "fixed_tags": dict(fixed_tags.most_common()),
        "worsened_tags": dict(worsened_tags.most_common()),
        "fixed_mode_goal": {
            f"{mode}/{goal}": count for (mode, goal), count in fixed_mode_goal.most_common()
        },
        "worsened_mode_goal": {
            f"{mode}/{goal}": count for (mode, goal), count in worsened_mode_goal.most_common()
        },
        "fixed_examples": fixed_by_model,
        "worsened_examples": worsened_by_model,
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "count": payload["count"],
        "model_same": payload["model_same"],
        "baseline_same": payload["baseline_same"],
        "fixed_by_model": payload["fixed_by_model"],
        "worsened_by_model": payload["worsened_by_model"],
        "net_gain": payload["net_gain"],
        "output": args.output,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
