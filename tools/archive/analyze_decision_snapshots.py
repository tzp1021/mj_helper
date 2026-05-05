#!/usr/bin/env python3
import argparse
import json
from collections import Counter
from pathlib import Path

from review_discard_overrides import classify_override
from review_operation_thresholds import classify_case, rejection_template


def load_snapshots(path):
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def candidate_gap(snapshot):
    candidates = (snapshot or {}).get("candidates") or []
    if len(candidates) < 2:
        return None
    first = candidates[0]
    second = candidates[1]
    if first.get("shanten") != second.get("shanten"):
        return None
    return {
        "ukeire_gap": first.get("ukeire", 0) - second.get("ukeire", 0),
        "danger_gap": round(second.get("danger", 0.0) - first.get("danger", 0.0), 2),
        "discard_a": first.get("tile_display") or first.get("tile"),
        "discard_b": second.get("tile_display") or second.get("tile"),
    }


def summarize(rows):
    total = len(rows)
    triggers = Counter()
    recommended_discards = Counter()
    operation_by_action = Counter()
    review_by_action = Counter()
    likely_release_actions = Counter()
    likely_release_tags = Counter()
    likely_release_signals = Counter()
    likely_release_patterns = Counter()
    likely_release_patterns_by_action = {
        "chi": Counter(),
        "peng": Counter(),
        "other": Counter(),
    }
    reasonable_reject_templates = Counter()
    reasonable_reject_actions = Counter()
    discard_tag_counter = Counter()
    risky_value_discards = []
    risky_value_patterns = Counter()
    discard_policy_reasons = Counter()
    discard_policy_buckets = Counter()
    discard_policy_cases = []
    riichi_templates = Counter()
    riichi_actions = Counter()
    riichi_template_cases = []
    riichi_review_buckets = Counter()
    riichi_review_cases = []
    low_confidence = []
    high_risk_pushes = []
    close_calls = []
    riichi_like_cases = []
    operation_cases = []
    review_operation_cases = []
    review_bucket_counter = Counter()
    phases = Counter()

    for row in rows:
        snapshot = row.get("snapshot") or {}
        action_plan = row.get("action_plan") or {}
        trigger = snapshot.get("trigger") or action_plan.get("trigger") or "unknown"
        triggers[trigger] += 1
        phases[snapshot.get("phase") or "unknown"] += 1
        discard = snapshot.get("rule_recommendation_display") or snapshot.get("rule_recommendation")
        if discard:
            recommended_discards[discard] += 1

        confidence = snapshot.get("confidence")
        if confidence is not None and confidence < 0.55:
            low_confidence.append({
                "index": row.get("index"),
                "round": snapshot.get("round"),
                "trigger": trigger,
                "confidence": confidence,
                "hand": "".join(snapshot.get("hand_display") or []),
            })

        top = (snapshot.get("candidates") or [{}])[0]
        policy_note = snapshot.get("discard_policy_note") or {}
        if top:
            danger = top.get("danger", 0.0)
            shanten = top.get("shanten")
            for tag in top.get("risk_reward_tags") or []:
                discard_tag_counter[tag] += 1
            if shanten is not None and shanten > 0 and danger >= 2.5:
                high_risk_pushes.append({
                    "index": row.get("index"),
                    "round": snapshot.get("round"),
                    "trigger": trigger,
                    "danger": danger,
                    "discard": top.get("tile_display") or top.get("tile"),
                })
            if "高总危险" in (top.get("risk_reward_tags") or []) and any(
                tag in (top.get("risk_reward_tags") or []) for tag in ("高打点路线", "强一向听", "高质量听牌")
            ):
                pattern_key = ",".join(sorted(top.get("risk_reward_tags") or [])[:4])
                risky_value_patterns[pattern_key] += 1
                risky_value_discards.append({
                    "index": row.get("index"),
                    "round": snapshot.get("round"),
                    "trigger": trigger,
                    "discard": top.get("tile_display") or top.get("tile"),
                    "danger": danger,
                    "tags": top.get("risk_reward_tags") or [],
                })
        if policy_note:
            discard_policy_reasons[policy_note.get("reason") or "unknown"] += 1
            policy_bucket = classify_override(policy_note, top, snapshot)
            discard_policy_buckets[policy_bucket] += 1
            discard_policy_cases.append({
                "index": row.get("index"),
                "round": snapshot.get("round"),
                "trigger": trigger,
                "reason": policy_note.get("reason"),
                "bucket": policy_bucket,
                "from_tile": policy_note.get("from_tile"),
                "to_tile": policy_note.get("to_tile"),
                "score_gap": policy_note.get("score_gap"),
                "pressure": policy_note.get("pressure"),
                "tilt": policy_note.get("tilt"),
                "preserve_reason": policy_note.get("preserve_reason"),
            })

        gap = candidate_gap(snapshot)
        if gap and abs(gap["ukeire_gap"]) <= 2 and abs(gap["danger_gap"]) <= 0.5:
            close_calls.append({
                "index": row.get("index"),
                "round": snapshot.get("round"),
                "trigger": trigger,
                **gap,
            })

        suggestion = row.get("suggestion") or ""
        if "立直" in suggestion or "默听" in suggestion:
            tenpai_analysis = row.get("tenpai_analysis") or {}
            template = tenpai_analysis.get("decision_template") or "unknown"
            push_value = tenpai_analysis.get("push_value")
            riichi_templates[template] += 1
            if "不建议立直" in suggestion or "偏向默听" in suggestion or "更建议默听" in suggestion or "按默听处理" in suggestion:
                riichi_actions["damaten"] += 1
            elif "建议立直" in suggestion or "默认建议立直" in suggestion:
                riichi_actions["riichi"] += 1
            review_bucket = None
            if template in {"threat_riichi_check", "threat_damaten"} and (push_value or 0.0) >= 3.6:
                review_bucket = "damaten_recheck"
            elif template in {"default_riichi", "push_value_riichi"} and 2.8 <= (push_value or 0.0) <= 4.4:
                review_bucket = "riichi_borderline"
            elif template in {"value_damaten", "high_value_damaten"} and (push_value or 0.0) >= 4.4:
                review_bucket = "value_damaten_recheck"
            if review_bucket:
                riichi_review_buckets[review_bucket] += 1
            riichi_template_cases.append({
                "index": row.get("index"),
                "round": snapshot.get("round"),
                "trigger": trigger,
                "template": template,
                "push_value": push_value,
                "template_note": tenpai_analysis.get("template_note"),
                "excerpt": suggestion.splitlines()[-1],
            })
            if review_bucket:
                riichi_review_cases.append({
                    "index": row.get("index"),
                    "round": snapshot.get("round"),
                    "trigger": trigger,
                    "template": template,
                    "review_bucket": review_bucket,
                    "push_value": push_value,
                    "template_note": tenpai_analysis.get("template_note"),
                    "excerpt": suggestion.splitlines()[-1],
                })
            riichi_like_cases.append({
                "index": row.get("index"),
                "round": snapshot.get("round"),
                "trigger": trigger,
                "confidence": snapshot.get("confidence"),
                "excerpt": suggestion.splitlines()[-1],
            })
        action_plan = row.get("action_plan") or {}
        if action_plan.get("kind") == "operation":
            case = {
                "index": row.get("index"),
                "round": snapshot.get("round"),
                "trigger": trigger,
                "action": action_plan.get("action"),
                "recommended": action_plan.get("recommended"),
                "call_score": action_plan.get("call_score"),
                "yaku_tags": action_plan.get("yaku_tags") or [],
                "call_breakdown": action_plan.get("call_breakdown") or {},
                "excerpt": suggestion.splitlines()[-1],
            }
            operation_cases.append(case)
            operation_by_action[case["action"] or "unknown"] += 1
            if (
                not case["recommended"]
                and (case.get("call_score") or -999) >= 4.5
                and (
                    (case["call_breakdown"].get("yaku_gain") or 0.0) >= 4.0
                    or (case["call_breakdown"].get("tenpai_bonus") or 0.0) >= 2.0
                )
            ):
                case["review_bucket"] = classify_case({
                    "call_score": float(case.get("call_score") or 0.0),
                    "yaku_gain": float(case["call_breakdown"].get("yaku_gain") or 0.0),
                    "tenpai_bonus": float(case["call_breakdown"].get("tenpai_bonus") or 0.0),
                    "danger_loss": float(case["call_breakdown"].get("danger_loss") or 0.0),
                })
                review_operation_cases.append(case)
                review_by_action[case["action"] or "unknown"] += 1
                review_bucket_counter[case["review_bucket"]] += 1
                if case["review_bucket"] == "likely_release":
                    likely_release_actions[case["action"] or "unknown"] += 1
                    for tag in case["yaku_tags"]:
                        likely_release_tags[tag] += 1
                    pattern_key = f"{case['action'] or 'unknown'}|" + ",".join(sorted(case["yaku_tags"])[:3])
                    likely_release_patterns[pattern_key] += 1
                    action_key = case["action"] if case["action"] in ("chi", "peng") else "other"
                    likely_release_patterns_by_action[action_key][pattern_key] += 1
                    breakdown = case["call_breakdown"]
                    if (breakdown.get("tenpai_bonus") or 0.0) >= 2.0:
                        likely_release_signals["high_tenpai_bonus"] += 1
                    if (breakdown.get("yaku_gain") or 0.0) >= 4.0:
                        likely_release_signals["high_yaku_gain"] += 1
                    if (breakdown.get("danger_loss") or 0.0) <= 1.2:
                        likely_release_signals["low_danger_loss"] += 1
                else:
                    reasonable_reject_actions[case["action"] or "unknown"] += 1
                    reasonable_reject_templates[rejection_template({
                        "call_score": float(case.get("call_score") or 0.0),
                        "yaku_gain": float(case["call_breakdown"].get("yaku_gain") or 0.0),
                        "tenpai_bonus": float(case["call_breakdown"].get("tenpai_bonus") or 0.0),
                        "danger_loss": float(case["call_breakdown"].get("danger_loss") or 0.0),
                    })] += 1

    operation_cases.sort(key=lambda item: item.get("call_score") or -999, reverse=True)
    review_operation_cases.sort(key=lambda item: item.get("call_score") or -999, reverse=True)

    return {
        "total_rows": total,
        "by_trigger": triggers.most_common(10),
        "by_phase": phases.most_common(),
        "top_discards": recommended_discards.most_common(10),
        "operation_by_action": operation_by_action.most_common(),
        "review_by_action": review_by_action.most_common(),
        "review_buckets": review_bucket_counter.most_common(),
        "likely_release_actions": likely_release_actions.most_common(),
        "likely_release_tags": likely_release_tags.most_common(10),
        "likely_release_signals": likely_release_signals.most_common(),
        "likely_release_patterns": likely_release_patterns.most_common(10),
        "likely_release_patterns_by_action": {
            key: counter.most_common(10) for key, counter in likely_release_patterns_by_action.items()
        },
        "reasonable_reject_actions": reasonable_reject_actions.most_common(),
        "reasonable_reject_templates": reasonable_reject_templates.most_common(),
        "discard_tags": discard_tag_counter.most_common(),
        "risky_value_patterns": risky_value_patterns.most_common(10),
        "risky_value_discards": risky_value_discards[:20],
        "discard_policy_reasons": discard_policy_reasons.most_common(),
        "discard_policy_buckets": discard_policy_buckets.most_common(),
        "discard_policy_cases": discard_policy_cases[:20],
        "riichi_templates": riichi_templates.most_common(),
        "riichi_actions": riichi_actions.most_common(),
        "riichi_template_cases": riichi_template_cases[:20],
        "riichi_review_buckets": riichi_review_buckets.most_common(),
        "riichi_review_cases": riichi_review_cases[:20],
        "low_confidence": low_confidence[:20],
        "high_risk_pushes": high_risk_pushes[:20],
        "close_calls": close_calls[:20],
        "riichi_like_cases": riichi_like_cases[:20],
        "operation_cases": operation_cases[:20],
        "review_operation_cases": review_operation_cases[:20],
    }


def print_summary(summary):
    print(f"rows: {summary['total_rows']}")
    print("")
    print("triggers:")
    for key, value in summary["by_trigger"]:
        print(f"  {key}: {value}")
    print("")
    print("phases:")
    for key, value in summary["by_phase"]:
        print(f"  {key}: {value}")
    print("")
    print("top discards:")
    for key, value in summary["top_discards"]:
        print(f"  {key}: {value}")
    print("")
    print("operation by action:")
    for key, value in summary["operation_by_action"]:
        print(f"  {key}: {value}")
    print("")
    print("review by action:")
    for key, value in summary["review_by_action"]:
        print(f"  {key}: {value}")
    print("")
    print("review buckets:")
    for key, value in summary["review_buckets"]:
        print(f"  {key}: {value}")
    print("")
    print("likely release actions:")
    for key, value in summary["likely_release_actions"]:
        print(f"  {key}: {value}")
    print("")
    print("likely release tags:")
    for key, value in summary["likely_release_tags"]:
        print(f"  {key}: {value}")
    print("")
    print("likely release signals:")
    for key, value in summary["likely_release_signals"]:
        print(f"  {key}: {value}")
    print("")
    print("likely release patterns:")
    for key, value in summary["likely_release_patterns"]:
        print(f"  {key}: {value}")
    print("")
    print("likely release patterns by action:")
    for action, items in summary["likely_release_patterns_by_action"].items():
        print(f"  {action}:")
        for key, value in items:
            print(f"    {key}: {value}")
    print("")
    print("reasonable reject actions:")
    for key, value in summary["reasonable_reject_actions"]:
        print(f"  {key}: {value}")
    print("")
    print("reasonable reject templates:")
    for key, value in summary["reasonable_reject_templates"]:
        print(f"  {key}: {value}")
    print("")
    print("discard tags:")
    for key, value in summary["discard_tags"]:
        print(f"  {key}: {value}")
    print("")
    print("risky value patterns:")
    for key, value in summary["risky_value_patterns"]:
        print(f"  {key}: {value}")
    print("")
    print("riichi actions:")
    for key, value in summary["riichi_actions"]:
        print(f"  {key}: {value}")
    print("")
    print("riichi templates:")
    for key, value in summary["riichi_templates"]:
        print(f"  {key}: {value}")
    print("")
    print("riichi review buckets:")
    for key, value in summary["riichi_review_buckets"]:
        print(f"  {key}: {value}")
    print("")
    print("discard policy reasons:")
    for key, value in summary["discard_policy_reasons"]:
        print(f"  {key}: {value}")
    print("")
    print("discard policy buckets:")
    for key, value in summary["discard_policy_buckets"]:
        print(f"  {key}: {value}")
    print("")
    print("low confidence cases:")
    for item in summary["low_confidence"]:
        print(f"  [{item['index']}] {item['round']} {item['trigger']} conf={item['confidence']} hand={item['hand']}")
    print("")
    print("high risk pushes:")
    for item in summary["high_risk_pushes"]:
        print(f"  [{item['index']}] {item['round']} {item['trigger']} discard={item['discard']} danger={item['danger']}")
    print("")
    print("riichi template cases:")
    for item in summary["riichi_template_cases"]:
        print(
            f"  [{item['index']}] {item['round']} {item['trigger']} "
            f"{item['template']} push={item['push_value']} {item['excerpt']}"
            + (
                f" note={item['template_note']}"
                if item.get("template_note") else ""
            )
        )
    print("")
    print("riichi review cases:")
    for item in summary["riichi_review_cases"]:
        print(
            f"  [{item['index']}] {item['round']} {item['trigger']} "
            f"{item['template']}/{item['review_bucket']} push={item['push_value']} {item['excerpt']}"
        )
    print("")
    print("risky value discards:")
    for item in summary["risky_value_discards"]:
        print(
            f"  [{item['index']}] {item['round']} {item['trigger']} "
            f"discard={item['discard']} danger={item['danger']} tags={','.join(item['tags'])}"
        )
    print("")
    print("discard policy cases:")
    for item in summary["discard_policy_cases"]:
        print(
            f"  [{item['index']}] {item['round']} {item['trigger']} "
            f"{item['reason']}/{item['bucket']} {item['from_tile']}->{item['to_tile']} "
            f"gap={item['score_gap']} pressure={item['pressure']} tilt={item['tilt']}"
            + (
                f" preserve={item['preserve_reason']}"
                if item.get("preserve_reason") else ""
            )
        )
    print("")
    print("close calls:")
    for item in summary["close_calls"]:
        print(
            f"  [{item['index']}] {item['round']} {item['trigger']} "
            f"{item['discard_a']} vs {item['discard_b']} ukeire_gap={item['ukeire_gap']} danger_gap={item['danger_gap']}"
        )
    print("")
    print("riichi-like cases:")
    for item in summary["riichi_like_cases"]:
        print(f"  [{item['index']}] {item['round']} {item['trigger']} conf={item['confidence']} {item['excerpt']}")
    print("")
    print("operation cases:")
    for item in summary["operation_cases"]:
        print(
            f"  [{item['index']}] {item['round']} {item['trigger']} "
            f"{item['action']} recommended={item['recommended']} call_score={item['call_score']} "
            f"bucket={item.get('review_bucket')} "
            f"tags={','.join(item['yaku_tags'])} "
            f"tenpai_bonus={item['call_breakdown'].get('tenpai_bonus')} "
            f"breakdown={item['call_breakdown']} {item['excerpt']}"
        )
    print("")
    print("review operation cases:")
    for item in summary["review_operation_cases"]:
        print(
            f"  [{item['index']}] {item['round']} {item['trigger']} "
            f"{item['action']} recommended={item['recommended']} call_score={item['call_score']} "
            f"tags={','.join(item['yaku_tags'])} "
            f"tenpai_bonus={item['call_breakdown'].get('tenpai_bonus')} "
            f"breakdown={item['call_breakdown']} {item['excerpt']}"
        )


def main():
    parser = argparse.ArgumentParser(description="Summarize majsoul helper decision snapshots.")
    parser.add_argument("snapshot_jsonl", help="Path to snapshot jsonl exported by majsoul_live_helper.py")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON summary")
    args = parser.parse_args()

    summary = summarize(load_snapshots(args.snapshot_jsonl))
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    print_summary(summary)


if __name__ == "__main__":
    main()
