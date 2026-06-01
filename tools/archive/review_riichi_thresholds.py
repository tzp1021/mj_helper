#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def load_rows(path):
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def classify_riichi_case(tenpai_analysis):
    template = (tenpai_analysis or {}).get("decision_template") or "unknown"
    push_value = float((tenpai_analysis or {}).get("push_value") or 0.0)
    if template in {"threat_riichi_check", "threat_damaten"} and push_value >= 3.6:
        return "damaten_recheck"
    if template in {"default_riichi", "push_value_riichi"} and 2.8 <= push_value <= 4.4:
        return "riichi_borderline"
    if template in {"value_damaten", "high_value_damaten"} and push_value >= 4.4:
        return "value_damaten_recheck"
    return None


def summarize(rows):
    cases = []
    for row in rows:
        suggestion = row.get("suggestion") or ""
        if "立直" not in suggestion and "默听" not in suggestion:
            continue
        tenpai_analysis = row.get("tenpai_analysis") or {}
        bucket = classify_riichi_case(tenpai_analysis)
        if not bucket:
            continue
        snapshot = row.get("snapshot") or {}
        cases.append({
            "index": row.get("index"),
            "round": snapshot.get("round"),
            "trigger": snapshot.get("trigger"),
            "bucket": bucket,
            "template": tenpai_analysis.get("decision_template"),
            "push_value": tenpai_analysis.get("push_value"),
            "template_note": tenpai_analysis.get("template_note"),
            "excerpt": suggestion.splitlines()[-1] if suggestion else "",
        })
    cases.sort(key=lambda item: item.get("push_value") or 0.0, reverse=True)
    return cases


def main():
    parser = argparse.ArgumentParser(description="Review borderline riichi/damaten cases from snapshot jsonl.")
    parser.add_argument("snapshot_jsonl", help="Path to snapshot jsonl")
    parser.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()

    rows = summarize(load_rows(args.snapshot_jsonl))
    print(f"riichi review cases: {min(len(rows), args.limit)} / {len(rows)}")
    for item in rows[:args.limit]:
        print(
            f"[{item['index']}] {item['round']} {item['trigger']} "
            f"{item['bucket']} template={item['template']} push={item['push_value']} "
            f"{item['excerpt']}"
            + (
                f" note={item['template_note']}"
                if item.get("template_note") else ""
            )
        )


if __name__ == "__main__":
    main()
