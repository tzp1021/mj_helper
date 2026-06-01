#!/usr/bin/env python3
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


TAG_ORDER = [
    "very_low_conf",
    "all_last",
    "placement_edge",
    "pressure",
    "very_close",
    "close",
    "neutral",
    "fold",
    "late_round",
]


def parse_args():
    parser = argparse.ArgumentParser(description="Analyze close-choice training rows vs holdout regressions.")
    parser.add_argument("training_rows_json")
    parser.add_argument("generalization_report_json")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    return parser.parse_args()


def ordered_tags(tags):
    tag_set = set(tags or [])
    return [tag for tag in TAG_ORDER if tag in tag_set]


def cluster_key(push_fold, hand_goal, tags):
    return (push_fold, hand_goal, tuple(ordered_tags(tags)))


def cluster_label(key):
    mode, goal, tags = key
    tail = " + ".join(tags) if tags else "no-tags"
    return f"{mode}/{goal} | {tail}"


def main():
    args = parse_args()
    training = json.loads(Path(args.training_rows_json).read_text(encoding="utf-8"))
    report = json.loads(Path(args.generalization_report_json).read_text(encoding="utf-8"))

    rows = training.get("rows") or []
    worsened = report.get("worsened_examples") or []
    fixed = report.get("fixed_examples") or []

    training_by_dataset = Counter()
    training_by_mode_goal = Counter()
    training_clusters = Counter()
    new_dataset_clusters = Counter()
    mode_goal_by_dataset = defaultdict(Counter)

    for row in rows:
        dataset = row["dataset"]
        mode = row["push_fold"]
        goal = row["hand_goal"]
        key = cluster_key(mode, goal, row.get("priority_tags") or [])
        training_by_dataset[dataset] += 1
        training_by_mode_goal[(mode, goal)] += 1
        training_clusters[key] += 1
        mode_goal_by_dataset[f"{mode}/{goal}"][dataset] += 1
        if dataset.startswith("tenhou_mjlog"):
            new_dataset_clusters[key] += 1

    worsened_clusters = Counter()
    worsened_by_mode_goal = Counter()
    for row in worsened:
        key = cluster_key(row["push_fold"], row["hand_goal"], row.get("priority_tags") or [])
        worsened_clusters[key] += 1
        worsened_by_mode_goal[(row["push_fold"], row["hand_goal"])] += 1

    fixed_clusters = Counter()
    for row in fixed:
        key = cluster_key(row["push_fold"], row["hand_goal"], row.get("priority_tags") or [])
        fixed_clusters[key] += 1

    suspicious = []
    for key, count in worsened_clusters.items():
        suspicious.append(
            {
                "cluster": cluster_label(key),
                "worsened_count": count,
                "training_count": training_clusters.get(key, 0),
                "new_dataset_training_count": new_dataset_clusters.get(key, 0),
                "fixed_count": fixed_clusters.get(key, 0),
            }
        )
    suspicious.sort(
        key=lambda item: (
            item["worsened_count"],
            item["new_dataset_training_count"],
            item["training_count"],
        ),
        reverse=True,
    )

    payload = {
        "training_count": len(rows),
        "worsened_count": len(worsened),
        "fixed_count": len(fixed),
        "training_by_dataset": dict(training_by_dataset.most_common()),
        "training_by_mode_goal": {
            f"{mode}/{goal}": count for (mode, goal), count in training_by_mode_goal.most_common()
        },
        "worsened_by_mode_goal": {
            f"{mode}/{goal}": count for (mode, goal), count in worsened_by_mode_goal.most_common()
        },
        "top_training_clusters": [
            {"cluster": cluster_label(key), "count": count}
            for key, count in training_clusters.most_common(15)
        ],
        "top_new_dataset_clusters": [
            {"cluster": cluster_label(key), "count": count}
            for key, count in new_dataset_clusters.most_common(15)
        ],
        "top_worsened_clusters": suspicious[:20],
        "mode_goal_dataset_mix": {
            mode_goal: dict(counter.most_common())
            for mode_goal, counter in sorted(mode_goal_by_dataset.items())
        },
    }

    md_lines = [
        "# close-choice 训练样本分簇分析",
        "",
        f"- training rows: `{len(rows)}`",
        f"- worsened holdout cases: `{len(worsened)}`",
        f"- fixed holdout cases: `{len(fixed)}`",
        "",
        "## 训练集来源分布",
        "",
    ]
    for name, count in training_by_dataset.most_common():
        md_lines.append(f"- `{name}`: `{count}`")

    md_lines += ["", "## 训练集 mode/goal 分布", ""]
    for (mode, goal), count in training_by_mode_goal.most_common():
        md_lines.append(f"- `{mode}/{goal}`: `{count}`")

    md_lines += ["", "## holdout 变差 mode/goal 分布", ""]
    for (mode, goal), count in worsened_by_mode_goal.most_common():
        md_lines.append(f"- `{mode}/{goal}`: `{count}`")

    md_lines += ["", "## 新数据主簇", ""]
    for item in payload["top_new_dataset_clusters"][:10]:
        md_lines.append(f"- `{item['cluster']}`: `{item['count']}`")

    md_lines += ["", "## holdout 变差主簇", ""]
    for item in suspicious[:12]:
        md_lines.append(
            f"- `{item['cluster']}`: worsened=`{item['worsened_count']}`, "
            f"training=`{item['training_count']}`, new_training=`{item['new_dataset_training_count']}`, "
            f"fixed=`{item['fixed_count']}`"
        )

    Path(args.output_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.output_md).write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "training_count": len(rows),
                "worsened_count": len(worsened),
                "output_json": args.output_json,
                "output_md": args.output_md,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
