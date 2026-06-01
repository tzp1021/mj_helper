#!/usr/bin/env python3
import argparse
import json
from collections import Counter
from pathlib import Path


def load_jsonl(path):
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def candidate_gap(snapshot):
    cands = snapshot.get("candidates") or []
    if len(cands) < 2:
        return None
    a, b = cands[0], cands[1]
    if a.get("shanten") != b.get("shanten"):
        return None
    return abs((a.get("mode_score") or 0) - (b.get("mode_score") or 0))


def classify_priority(snapshot):
    confidence = snapshot.get("confidence")
    mode = snapshot.get("push_fold")
    phase = snapshot.get("phase")
    place = snapshot.get("place")
    is_all_last = bool(snapshot.get("is_all_last"))
    pressure = snapshot.get("pressure")
    gap = candidate_gap(snapshot)
    score = 0
    tags = []

    if confidence is not None and confidence < 0.45:
        score += 5
        tags.append("very_low_conf")
    elif confidence is not None and confidence < 0.55:
        score += 3
        tags.append("low_conf")

    if gap is not None and gap <= 3:
        score += 5
        tags.append("very_close")
    elif gap is not None and gap <= 6:
        score += 3
        tags.append("close")

    if mode == "fold":
        score += 3
        tags.append("fold")
    elif mode == "neutral":
        score += 2
        tags.append("neutral")

    if is_all_last:
        score += 4
        tags.append("all_last")
        if place in (1, 4):
            score += 2
            tags.append("placement_edge")

    if pressure in ("较高", "很高"):
        score += 2
        tags.append("pressure")

    if phase == "后巡":
        score += 2
        tags.append("late_round")

    return score, tags


def main():
    parser = argparse.ArgumentParser(description="Select high-value replay cases for second-pass refinement.")
    parser.add_argument("snapshot_jsonl")
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--max-per-source", type=int, default=3)
    args = parser.parse_args()

    ranked = []
    tag_counter = Counter()
    for row in load_jsonl(args.snapshot_jsonl):
        snap = row.get("snapshot") or {}
        score, tags = classify_priority(snap)
        if score <= 0:
            continue
        for tag in tags:
            tag_counter[tag] += 1
        ranked.append({
            "source_file": row.get("source_file"),
            "index": row.get("index"),
            "round": snap.get("round"),
            "trigger": snap.get("trigger"),
            "push_fold": snap.get("push_fold"),
            "hand_goal": snap.get("hand_goal"),
            "confidence": snap.get("confidence"),
            "priority_score": score,
            "priority_tags": tags,
            "rule_recommendation": snap.get("rule_recommendation"),
            "rule_recommendation_display": snap.get("rule_recommendation_display"),
            "candidate_gap": candidate_gap(snap),
        })

    ranked.sort(
        key=lambda item: (
            -item["priority_score"],
            item["confidence"] if item["confidence"] is not None else 1.0,
            item["candidate_gap"] if item["candidate_gap"] is not None else 99,
        )
    )
    selected = []
    per_source = Counter()
    for item in ranked:
        source = item.get("source_file")
        if args.max_per_source is not None and source and per_source[source] >= args.max_per_source:
            continue
        selected.append(item)
        if source:
            per_source[source] += 1
        if len(selected) >= args.limit:
            break
    payload = {
        "count": len(selected),
        "source": args.snapshot_jsonl,
        "limit": args.limit,
        "max_per_source": args.max_per_source,
        "tag_counts": dict(tag_counter.most_common()),
        "cases": selected,
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "selected": len(selected),
                "output": args.output,
                "top_tags": dict(tag_counter.most_common(10)),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
