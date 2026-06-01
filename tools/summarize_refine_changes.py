#!/usr/bin/env python3
import argparse
import json
from collections import Counter
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Summarize changed recommendations in fast-vs-refined comparisons.")
    parser.add_argument("compare_json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    payload = json.loads(Path(args.compare_json).read_text(encoding="utf-8"))
    rows = payload.get("rows") or []
    changed = [row for row in rows if not row.get("same_recommendation")]

    by_tag = Counter()
    by_fast = Counter()
    by_refined = Counter()
    by_push_fold = Counter()
    by_pair = Counter()

    for row in changed:
        for tag in row.get("priority_tags") or []:
            by_tag[tag] += 1
        by_fast[row.get("fast_recommendation_display") or row.get("fast_recommendation") or "?"] += 1
        by_refined[row.get("refined_recommendation_display") or row.get("refined_recommendation") or "?"] += 1
        by_push_fold[row.get("fast_push_fold") or "?"] += 1
        pair = f"{row.get('fast_recommendation_display') or row.get('fast_recommendation')} -> {row.get('refined_recommendation_display') or row.get('refined_recommendation')}"
        by_pair[pair] += 1

    summary = {
        "count": len(rows),
        "changed_count": len(changed),
        "changed_rate": round(len(changed) / len(rows), 3) if rows else 0.0,
        "by_tag": dict(by_tag.most_common()),
        "by_push_fold": dict(by_push_fold.most_common()),
        "by_fast": dict(by_fast.most_common()),
        "by_refined": dict(by_refined.most_common()),
        "by_pair": dict(by_pair.most_common()),
        "changed_rows": changed,
    }
    Path(args.output).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "changed_count": len(changed),
        "changed_rate": summary["changed_rate"],
        "top_tags": dict(by_tag.most_common(10)),
        "output": args.output,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
