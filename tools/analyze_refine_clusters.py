#!/usr/bin/env python3
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def load_compare(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload.get("rows") or []


def canonical_tags(row):
    return tuple(sorted(row.get("priority_tags") or []))


def cluster_key(row):
    return (
        canonical_tags(row),
        row.get("fast_push_fold"),
        row.get("refined_push_fold"),
        row.get("fast_hand_goal"),
        row.get("refined_hand_goal"),
    )


def format_example(row):
    source = Path(row.get("source_file") or "").name
    return {
        "source_file": source,
        "index": row.get("index"),
        "fast": row.get("fast_recommendation_display") or row.get("fast_recommendation"),
        "refined": row.get("refined_recommendation_display") or row.get("refined_recommendation"),
    }


def build_report(rows, top_n=12, examples_per_cluster=3):
    changed = [row for row in rows if not row.get("same_recommendation")]
    cluster_counter = Counter()
    pair_counter = Counter()
    tag_counter = Counter()
    pushfold_counter = Counter()
    goal_shift_counter = Counter()
    examples = defaultdict(list)

    for row in changed:
        key = cluster_key(row)
        cluster_counter[key] += 1
        pair_counter[(row.get("fast_recommendation_display"), row.get("refined_recommendation_display"))] += 1
        pushfold_counter[(row.get("fast_push_fold"), row.get("refined_push_fold"))] += 1
        goal_shift_counter[(row.get("fast_hand_goal"), row.get("refined_hand_goal"))] += 1
        for tag in row.get("priority_tags") or []:
            tag_counter[tag] += 1
        if len(examples[key]) < examples_per_cluster:
            examples[key].append(format_example(row))

    top_clusters = []
    for key, count in cluster_counter.most_common(top_n):
        tags, fast_pf, refined_pf, fast_goal, refined_goal = key
        top_clusters.append(
            {
                "count": count,
                "share": round(count / len(changed), 3) if changed else 0.0,
                "tags": list(tags),
                "fast_push_fold": fast_pf,
                "refined_push_fold": refined_pf,
                "fast_hand_goal": fast_goal,
                "refined_hand_goal": refined_goal,
                "examples": examples[key],
            }
        )

    return {
        "rows": len(rows),
        "changed": len(changed),
        "changed_rate": round(len(changed) / len(rows), 3) if rows else 0.0,
        "top_tags": dict(tag_counter.most_common(12)),
        "push_fold_pairs": {f"{a}->{b}": c for (a, b), c in pushfold_counter.most_common()},
        "hand_goal_pairs": {f"{a}->{b}": c for (a, b), c in goal_shift_counter.most_common()},
        "top_recommendation_pairs": {
            f"{a}->{b}": c for (a, b), c in pair_counter.most_common(12)
        },
        "top_clusters": top_clusters,
    }


def write_markdown(report, path):
    lines = []
    lines.append("# Refine Cluster Analysis")
    lines.append("")
    lines.append(f"- Total compared: `{report['rows']}`")
    lines.append(f"- Changed: `{report['changed']}`")
    lines.append(f"- Changed rate: `{report['changed_rate']}`")
    lines.append("")
    lines.append("## Top Tags")
    lines.append("")
    for tag, count in report["top_tags"].items():
        lines.append(f"- `{tag}`: `{count}`")
    lines.append("")
    lines.append("## Push/Fold Pairs")
    lines.append("")
    for key, count in report["push_fold_pairs"].items():
        lines.append(f"- `{key}`: `{count}`")
    lines.append("")
    lines.append("## Hand Goal Pairs")
    lines.append("")
    for key, count in report["hand_goal_pairs"].items():
        lines.append(f"- `{key}`: `{count}`")
    lines.append("")
    lines.append("## Top Recommendation Pairs")
    lines.append("")
    for key, count in report["top_recommendation_pairs"].items():
        lines.append(f"- `{key}`: `{count}`")
    lines.append("")
    lines.append("## Top Clusters")
    lines.append("")
    for idx, cluster in enumerate(report["top_clusters"], start=1):
        lines.append(f"### Cluster {idx}")
        lines.append("")
        lines.append(f"- Count: `{cluster['count']}`")
        lines.append(f"- Share: `{cluster['share']}`")
        lines.append(f"- Tags: `{', '.join(cluster['tags'])}`")
        lines.append(
            f"- Push/Fold: `{cluster['fast_push_fold']} -> {cluster['refined_push_fold']}`"
        )
        lines.append(
            f"- Hand Goal: `{cluster['fast_hand_goal']} -> {cluster['refined_hand_goal']}`"
        )
        lines.append("- Examples:")
        for example in cluster["examples"]:
            lines.append(
                f"  - `{example['source_file']}#{example['index']}`: `{example['fast']} -> {example['refined']}`"
            )
        lines.append("")

    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Cluster changed cases from fast-vs-refined comparisons.")
    parser.add_argument("compare_json")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    parser.add_argument("--top-n", type=int, default=12)
    args = parser.parse_args()

    rows = load_compare(args.compare_json)
    report = build_report(rows, top_n=args.top_n)
    Path(args.output_json).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_markdown(report, args.output_md)
    print(
        json.dumps(
            {
                "rows": report["rows"],
                "changed": report["changed"],
                "changed_rate": report["changed_rate"],
                "output_json": args.output_json,
                "output_md": args.output_md,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
