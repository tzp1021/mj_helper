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


def classify_override(note, candidate, snapshot=None):
    reason = (note or {}).get("reason")
    bucket = (note or {}).get("bucket")
    if reason == "preserve_risky_push":
        return bucket or "preserve_risky_push"
    if bucket:
        return bucket
    danger = float((candidate or {}).get("danger") or 0.0)
    tags = set((candidate or {}).get("risk_reward_tags") or [])
    if reason == "same_shanten_safer_override":
        if "高总危险" in tags and ("高打点路线" in tags or "强一向听" in tags):
            return "value_push_overridden"
        return "same_shanten_safer_override"
    if reason == "high_pressure_safer_override":
        return "high_pressure_override"
    if danger >= 2.5 and "高质量听牌" in tags:
        return "tenpai_push_overridden"
    return reason or "unknown"


def summarize(rows):
    overrides = []
    for row in rows:
        snapshot = row.get("snapshot") or {}
        note = snapshot.get("discard_policy_note") or {}
        if not note:
            continue
        top = (snapshot.get("candidates") or [{}])[0]
        overrides.append({
            "index": row.get("index"),
            "round": snapshot.get("round"),
            "trigger": snapshot.get("trigger"),
            "reason": note.get("reason"),
            "bucket": classify_override(note, top, snapshot),
            "from_tile": note.get("from_tile"),
            "to_tile": note.get("to_tile"),
            "score_gap": note.get("score_gap"),
            "pressure": note.get("pressure"),
            "tilt": note.get("tilt"),
            "tags": top.get("risk_reward_tags") or [],
            "danger": top.get("danger"),
            "preserve_reason": note.get("preserve_reason"),
        })
    overrides.sort(key=lambda item: (item["pressure"] or 0, item["score_gap"] or 0), reverse=True)
    return overrides


def main():
    parser = argparse.ArgumentParser(description="Review discard safety override cases from snapshot jsonl.")
    parser.add_argument("snapshot_jsonl", help="Path to snapshot jsonl")
    parser.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()

    rows = summarize(load_rows(args.snapshot_jsonl))
    print(f"overrides: {min(len(rows), args.limit)} / {len(rows)}")
    for item in rows[:args.limit]:
        print(
            f"[{item['index']}] {item['round']} {item['trigger']} "
            f"{item['bucket']} {item['from_tile']}->{item['to_tile']} "
            f"gap={item['score_gap']} pressure={item['pressure']} tilt={item['tilt']} "
            f"danger={item['danger']} tags={','.join(item['tags'])}"
            + (
                f" preserve={item['preserve_reason']}"
                if item.get("preserve_reason") else ""
            )
        )


if __name__ == "__main__":
    main()
