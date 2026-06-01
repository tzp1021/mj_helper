#!/usr/bin/env python3
import argparse
import json
from collections import Counter
from bisect import bisect_right
from pathlib import Path


def decode_seer_action(action):
    if action is None:
        return None
    if 1 <= action <= 9:
        return {"kind": "op", "action": action, "tile": None}
    if 100 <= action < 200:
        return {"kind": "discard", "action": action, "tile": number_to_tile(action - 100), "riichi": False}
    if 200 <= action < 300:
        return {"kind": "discard", "action": action, "tile": number_to_tile(action - 200), "riichi": True}
    if 300 <= action < 400:
        return {"kind": "gang", "action": action, "tile": number_to_tile(action - 300)}
    return None


def number_to_tile(value):
    if 11 <= value <= 19:
        return f"{value - 10}m"
    if 21 <= value <= 29:
        return f"{value - 20}p"
    if 31 <= value <= 39:
        return f"{value - 30}s"
    if 41 <= value <= 47:
        return f"{value - 40}z"
    return None


def load_snapshots(path):
    rows = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        rows[row["index"]] = row
    return rows


def actual_action_seat(event):
    actual = event.get("actual_action") or {}
    if actual.get("seat") is not None:
        return actual.get("seat")
    raw_action = (actual.get("raw_action") or {})
    for key in ("user_input", "user_event", "operation"):
        payload = raw_action.get(key) or actual.get(key) or {}
        if isinstance(payload, dict) and payload.get("seat") is not None:
            return payload.get("seat")
    return None


def actual_action_operation(event):
    actual = event.get("actual_action") or {}
    operation = actual.get("operation")
    if isinstance(operation, dict):
        return operation
    raw_action = actual.get("raw_action") or {}
    user_input = raw_action.get("user_input") or actual.get("user_input") or {}
    operation = user_input.get("operation")
    if isinstance(operation, dict):
        return operation
    return None


def compare_file(aligned_path, snapshot_path, player_name):
    aligned = json.loads(Path(aligned_path).read_text(encoding="utf-8"))
    snapshots = load_snapshots(snapshot_path)
    snapshot_indices = sorted(snapshots)
    accounts = (aligned.get("head") or {}).get("accounts") or []
    self_seat = next((acc.get("seat") for acc in accounts if acc.get("nickname") == player_name), None)
    if self_seat is None:
        raise ValueError(f"player {player_name!r} not found in {aligned_path}")

    matched = []
    mismatch_tags = Counter()
    mismatch_rounds = Counter()
    mismatch_templates = Counter()
    compare_kind = Counter()
    seat_mismatch_count = 0
    non_actionable_skipped = 0

    for event in aligned.get("aligned_events") or []:
        record_index = event.get("record_index")
        if record_index is None:
            continue
        recommend = None
        for item in event.get("recommends") or []:
            seat = item.get("seat", 0)
            if seat == self_seat:
                recommend = item
                break
        if not recommend:
            continue
        preds = recommend.get("predictions") or []
        if not preds:
            continue
        decoded_preds = [decode_seer_action(pred.get("action")) for pred in preds[:3]]
        decoded_preds = [item for item in decoded_preds if item]
        if not decoded_preds:
            continue
        event_seat = actual_action_seat(event)
        operation = actual_action_operation(event)
        if event_seat is None or event_seat != self_seat or not operation:
            non_actionable_skipped += 1
            continue
        if operation.get("type") != 1 or not operation.get("tile"):
            non_actionable_skipped += 1
            continue

        snap_pos = bisect_right(snapshot_indices, record_index) - 1
        if snap_pos < 0:
            continue
        snapshot_index = snapshot_indices[snap_pos]
        snap = snapshots[snapshot_index]

        snapshot = snap.get("snapshot") or {}
        action_plan = snap.get("action_plan") or {}
        tenpai = snap.get("tenpai_analysis") or {}
        snapshot_self_seat = snapshot.get("self_seat")
        if snapshot_self_seat is not None and snapshot_self_seat != self_seat:
            seat_mismatch_count += 1
            continue
        round_name = snapshot.get("round") or event.get("round") or "unknown"

        if decoded_preds[0]["kind"] == "discard":
            ours_tile = snapshot.get("rule_recommendation")
            if not ours_tile:
                continue
            compare_kind["discard"] += 1
            matched.append({
                "kind": "discard",
                "record_index": record_index,
                "snapshot_index": snapshot_index,
                "round": round_name,
                "ours": ours_tile,
                "seer_top": decoded_preds[0]["tile"],
                "seer_top3": [item["tile"] for item in decoded_preds if item.get("tile")],
                "actual": operation.get("tile"),
                "tags": ((snapshot.get("candidates") or [{}])[0].get("risk_reward_tags") or []),
                "template": tenpai.get("decision_template"),
                "title": snap.get("suggestion", "").splitlines()[0],
            })
        elif decoded_preds[0]["kind"] == "op":
            if action_plan.get("kind") != "operation":
                continue
            compare_kind["operation"] += 1
            matched.append({
                "kind": "operation",
                "record_index": record_index,
                "round": round_name,
                "ours": action_plan.get("action"),
                "ours_recommended": action_plan.get("recommended"),
                "seer_top": decoded_preds[0]["action"],
                "seer_top3": [item["action"] for item in decoded_preds],
                "tags": action_plan.get("yaku_tags") or [],
                "template": None,
                "title": snap.get("suggestion", "").splitlines()[-1],
            })

    exact = 0
    top3 = 0
    mismatches = []
    for item in matched:
        if item["kind"] == "discard":
            if item["ours"] == item["seer_top"]:
                exact += 1
            else:
                mismatch_rounds[item["round"]] += 1
                mismatch_templates[item.get("template") or "none"] += 1
                for tag in item.get("tags") or []:
                    mismatch_tags[tag] += 1
                mismatches.append(item)
            if item["ours"] in item["seer_top3"]:
                top3 += 1

    discard_total = compare_kind["discard"]
    return {
        "uuid": aligned.get("uuid"),
        "player_name": player_name,
        "self_seat": self_seat,
        "compare_kind": compare_kind,
        "seat_mismatch_skipped": seat_mismatch_count,
        "non_actionable_skipped": non_actionable_skipped,
        "discard_matched": discard_total,
        "discard_exact": exact,
        "discard_exact_rate": round(exact / discard_total, 3) if discard_total else None,
        "discard_top3": top3,
        "discard_top3_rate": round(top3 / discard_total, 3) if discard_total else None,
        "mismatch_rounds": mismatch_rounds.most_common(),
        "mismatch_tags": mismatch_tags.most_common(),
        "mismatch_templates": mismatch_templates.most_common(),
        "sample_mismatches": mismatches[:20],
    }


def main():
    parser = argparse.ArgumentParser(description="Analyze aligned Seer data against local snapshot recommendations.")
    parser.add_argument("aligned_dir", help="Directory containing *.aligned.json files")
    parser.add_argument("snapshot_dir", help="Directory containing *.snapshots.jsonl files")
    parser.add_argument("--player-name", default="Levey")
    args = parser.parse_args()

    results = []
    aligned_dir = Path(args.aligned_dir)
    snapshot_dir = Path(args.snapshot_dir)
    for aligned_path in sorted(aligned_dir.glob("*.aligned.json")):
        snapshot_path = snapshot_dir / aligned_path.name.replace(".aligned.json", ".snapshots.jsonl")
        if not snapshot_path.exists():
            continue
        result = compare_file(aligned_path, snapshot_path, args.player_name)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    if results:
        total = sum(item["discard_matched"] for item in results)
        exact = sum(item["discard_exact"] for item in results)
        top3 = sum(item["discard_top3"] for item in results)
        seat_mismatch = sum(item.get("seat_mismatch_skipped", 0) for item in results)
        non_actionable = sum(item.get("non_actionable_skipped", 0) for item in results)
        print("")
        print(json.dumps({
            "files": len(results),
            "seat_mismatch_skipped": seat_mismatch,
            "non_actionable_skipped": non_actionable,
            "discard_matched": total,
            "discard_exact": exact,
            "discard_exact_rate": round(exact / total, 3) if total else None,
            "discard_top3": top3,
            "discard_top3_rate": round(top3 / total, 3) if total else None,
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
