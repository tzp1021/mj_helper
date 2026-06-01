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


def iter_operation_rows(rows):
    for row in rows:
        plan = row.get("action_plan") or {}
        if plan.get("kind") != "operation":
            continue
        yield {
            "index": row.get("index"),
            "round": (row.get("snapshot") or {}).get("round"),
            "trigger": (row.get("snapshot") or {}).get("trigger"),
            "action": plan.get("action"),
            "recommended": bool(plan.get("recommended")),
            "call_score": float(plan.get("call_score") or 0.0),
            "yaku_gain": float((plan.get("call_breakdown") or {}).get("yaku_gain") or 0.0),
            "tenpai_bonus": float((plan.get("call_breakdown") or {}).get("tenpai_bonus") or 0.0),
            "danger_loss": float((plan.get("call_breakdown") or {}).get("danger_loss") or 0.0),
            "tags": plan.get("yaku_tags") or [],
            "reason": (row.get("suggestion") or "").splitlines()[-1] if row.get("suggestion") else "",
        }


def select_cases(rows, min_call_score, min_yaku_gain, min_tenpai_bonus):
    selected = []
    for item in iter_operation_rows(rows):
        if item["recommended"]:
            continue
        if item["call_score"] < min_call_score:
            continue
        if item["yaku_gain"] < min_yaku_gain and item["tenpai_bonus"] < min_tenpai_bonus:
            continue
        selected.append(item)
    selected.sort(key=lambda item: (item["call_score"], item["yaku_gain"], item["tenpai_bonus"]), reverse=True)
    return selected


def classify_case(item):
    if item["danger_loss"] >= 2.0:
        return "reasonable_reject"
    if item["call_score"] >= 7.0 and (item["yaku_gain"] >= 4.4 or item["tenpai_bonus"] >= 2.6):
        return "likely_release"
    if item["call_score"] >= 5.5 and item["danger_loss"] <= 1.2 and item["yaku_gain"] >= 4.0:
        return "likely_release"
    return "reasonable_reject"


def rejection_template(item):
    if item["danger_loss"] >= 2.0:
        return "high_danger_loss"
    if item["danger_loss"] >= 1.2 and item["tenpai_bonus"] < 2.0:
        return "danger_over_speed"
    if item["yaku_gain"] < 4.0 and item["tenpai_bonus"] < 2.0:
        return "weak_value_path"
    if item["yaku_gain"] >= 4.0 and item["danger_loss"] >= 1.0:
        return "value_but_risky"
    return "borderline_recheck"


def bucket_cases(selected):
    buckets = {
        "likely_release": [],
        "reasonable_reject": [],
    }
    for item in selected:
        buckets[classify_case(item)].append(item)
    return buckets


def main():
    parser = argparse.ArgumentParser(description="Review rejected operation cases that may deserve threshold tuning.")
    parser.add_argument("snapshot_jsonl", help="Path to snapshot jsonl")
    parser.add_argument("--min-call-score", type=float, default=4.5)
    parser.add_argument("--min-yaku-gain", type=float, default=4.0)
    parser.add_argument("--min-tenpai-bonus", type=float, default=2.0)
    parser.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()

    rows = load_rows(args.snapshot_jsonl)
    selected = select_cases(rows, args.min_call_score, args.min_yaku_gain, args.min_tenpai_bonus)
    buckets = bucket_cases(selected)
    print(f"selected: {min(len(selected), args.limit)} / {len(selected)}")
    for bucket_name in ("likely_release", "reasonable_reject"):
        print("")
        print(f"{bucket_name}: {len(buckets[bucket_name])}")
        for item in buckets[bucket_name][:args.limit]:
            print(
                f"[{item['index']}] {item['round']} {item['trigger']} "
                f"{item['action']} score={item['call_score']} "
                f"yaku_gain={item['yaku_gain']} tenpai_bonus={item['tenpai_bonus']} "
                f"danger_loss={item['danger_loss']} tags={','.join(item['tags'])}"
            )
            print(f"  {item['reason']}")


if __name__ == "__main__":
    main()
