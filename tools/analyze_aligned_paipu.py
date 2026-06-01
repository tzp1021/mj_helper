#!/usr/bin/env python3
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import parse_majsoul_har as pmh
from majsoul_live_helper import LiveGameState, decode_record_wrapper, record_accounts_mapping, record_to_action
from analyze_aligned_seer import actual_action_operation, actual_action_seat, decode_seer_action


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def tile_family(tile):
    if not tile:
        return "none"
    if tile[1] == "z":
        return "honor"
    if tile[0] in "19":
        return "terminal"
    return "middle"


def accumulate_counter(counter, items):
    for key, count in items or []:
        counter[key] += count


def accumulate_consensus_family_patterns(counter, items):
    for item in items or []:
        key = f"{item.get('ours')}->{item.get('actual')}"
        counter[key] += item.get("count", 0)


def actionable_events(aligned, player_name):
    accounts = ((aligned.get("head") or {}).get("accounts") or [])
    self_seat = next((acc.get("seat") for acc in accounts if acc.get("nickname") == player_name), None)
    if self_seat is None:
        raise ValueError(f"player {player_name!r} not found in {aligned.get('uuid')}")

    events = {}
    for event in aligned.get("aligned_events") or []:
        record_index = event.get("record_index")
        if record_index is None:
            continue
        if actual_action_seat(event) != self_seat:
            continue
        operation = actual_action_operation(event)
        if not operation or operation.get("type") != 1 or not operation.get("tile"):
            continue
        recommend = next(
            (item for item in (event.get("recommends") or []) if item.get("seat", 0) == self_seat and (item.get("predictions") or [])),
            None,
        )
        if not recommend:
            continue
        decoded_preds = [decode_seer_action(pred.get("action")) for pred in (recommend.get("predictions") or [])[:3]]
        decoded_preds = [item for item in decoded_preds if item and item.get("kind") == "discard" and item.get("tile")]
        if not decoded_preds:
            continue
        events[record_index] = {
            "record_index": record_index,
            "round": event.get("round"),
            "actual": operation.get("tile"),
            "seer_top": decoded_preds[0]["tile"],
            "seer_top3": [item["tile"] for item in decoded_preds],
        }
    return self_seat, events


def compare_one(aligned_path, paipu_path, player_name, max_record_index=None, suggestion_lookback=3):
    aligned = load_json(aligned_path)
    paipu = load_json(paipu_path)
    self_seat, events = actionable_events(aligned, player_name)
    if not events:
        return {
            "uuid": aligned.get("uuid"),
            "player_name": player_name,
            "self_seat": self_seat,
            "discard_matched": 0,
            "discard_exact": 0,
            "discard_exact_rate": None,
            "discard_top3": 0,
            "discard_top3_rate": None,
            "discard_actual_match": 0,
            "discard_actual_match_rate": None,
            "seer_actual_match": 0,
            "seer_actual_match_rate": None,
            "mismatch_rounds": [],
            "mismatch_tags": [],
            "mismatch_patterns": [],
            "consensus_mismatch_count": 0,
            "consensus_family_patterns": [],
            "sample_consensus_mismatches": [],
            "sample_mismatches": [],
        }
    max_event_index = max(events)
    if max_record_index is not None:
        max_event_index = min(max_event_index, max_record_index)
        events = {index: event for index, event in events.items() if index <= max_event_index}
        if not events:
            return {
                "uuid": aligned.get("uuid"),
                "player_name": player_name,
                "self_seat": self_seat,
                "discard_matched": 0,
                "discard_exact": 0,
                "discard_exact_rate": None,
                "discard_top3": 0,
                "discard_top3_rate": None,
                "discard_actual_match": 0,
                "discard_actual_match_rate": None,
                "seer_actual_match": 0,
                "seer_actual_match_rate": None,
                "mismatch_rounds": [],
                "mismatch_tags": [],
                "mismatch_patterns": [],
                "consensus_mismatch_count": 0,
                "consensus_family_patterns": [],
                "sample_consensus_mismatches": [],
                "sample_mismatches": [],
            }

    state = LiveGameState()
    state.seat_names = dict(sorted(record_accounts_mapping(paipu).items()))
    state.self_seat = self_seat
    schema = pmh.LiqiSchema(load_json(ROOT / "liqi.json"))
    actions = ((paipu.get("game_detail_records") or {}).get("actions") or [])
    suggestion_probe_indices = set()
    for event_index in events:
        start = max(0, event_index - max(1, suggestion_lookback))
        suggestion_probe_indices.update(range(start, event_index))

    latest_snapshot = None
    latest_snapshot_index = None
    latest_title = None
    matched = []
    mismatch_rounds = Counter()
    mismatch_tags = Counter()

    for index, item in enumerate(actions):
        if index > max_event_index:
            break
        payload = ((item.get("result") or {}).get("_base64"))
        if payload:
            wrapped = decode_record_wrapper(schema, payload)
            if wrapped:
                action = record_to_action(wrapped["short_name"], wrapped["data"], state.self_seat)
                if action:
                    suggestion = state.apply_action(
                        action,
                        index,
                        emit_suggestion=index in suggestion_probe_indices,
                    )
                    if suggestion:
                        latest_snapshot = state.last_decision_snapshot
                        latest_snapshot_index = index
                        latest_title = suggestion.splitlines()[0]
        event = events.get(index)
        if not event or latest_snapshot is None or latest_snapshot_index is None:
            continue
        ours = latest_snapshot.get("rule_recommendation")
        if not ours:
            continue
        matched.append({
            "record_index": index,
            "snapshot_index": latest_snapshot_index,
            "round": latest_snapshot.get("round") or event.get("round") or "unknown",
            "ours": ours,
            "seer_top": event["seer_top"],
            "seer_top3": event["seer_top3"],
            "actual": event["actual"],
            "tags": ((latest_snapshot.get("candidates") or [{}])[0].get("risk_reward_tags") or []),
            "title": latest_title,
        })

    exact = 0
    top3 = 0
    actual_match = 0
    seer_actual_match = 0
    mismatches = []
    mismatch_patterns = Counter()
    consensus_mismatches = []
    consensus_family_patterns = Counter()
    for item in matched:
        if item["ours"] == item["actual"]:
            actual_match += 1
        if item["seer_top"] == item["actual"]:
            seer_actual_match += 1
        if item["ours"] == item["seer_top"]:
            exact += 1
        else:
            mismatch_rounds[item["round"]] += 1
            for tag in item.get("tags") or []:
                mismatch_tags[tag] += 1
            if item["ours"] == item["actual"]:
                mismatch_patterns["ours_matches_actual"] += 1
            elif item["seer_top"] == item["actual"]:
                mismatch_patterns["seer_matches_actual"] += 1
            elif item["actual"] in item["seer_top3"]:
                mismatch_patterns["actual_in_seer_top3"] += 1
            elif item["ours"] in item["seer_top3"]:
                mismatch_patterns["ours_in_seer_top3"] += 1
            else:
                mismatch_patterns["full_split"] += 1
            mismatches.append(item)
            if item["ours"] != item["actual"] and (
                item["seer_top"] == item["actual"] or item["actual"] in item["seer_top3"]
            ):
                consensus_mismatches.append(item)
                consensus_family_patterns[(tile_family(item["ours"]), tile_family(item["actual"]))] += 1
        if item["ours"] in item["seer_top3"]:
            top3 += 1

    return {
        "uuid": aligned.get("uuid"),
        "player_name": player_name,
        "self_seat": self_seat,
        "discard_matched": len(matched),
        "discard_exact": exact,
        "discard_exact_rate": round(exact / len(matched), 3) if matched else None,
        "discard_top3": top3,
        "discard_top3_rate": round(top3 / len(matched), 3) if matched else None,
        "discard_actual_match": actual_match,
        "discard_actual_match_rate": round(actual_match / len(matched), 3) if matched else None,
        "seer_actual_match": seer_actual_match,
        "seer_actual_match_rate": round(seer_actual_match / len(matched), 3) if matched else None,
        "mismatch_rounds": mismatch_rounds.most_common(),
        "mismatch_tags": mismatch_tags.most_common(),
        "mismatch_patterns": mismatch_patterns.most_common(),
        "consensus_mismatch_count": len(consensus_mismatches),
        "consensus_family_patterns": [
            {"ours": ours, "actual": actual, "count": count}
            for (ours, actual), count in consensus_family_patterns.most_common()
        ],
        "sample_consensus_mismatches": consensus_mismatches[:10],
        "sample_mismatches": mismatches[:20],
    }


def main():
    parser = argparse.ArgumentParser(description="Replay paipu directly and compare actionable aligned Seer events.")
    parser.add_argument("aligned_dir")
    parser.add_argument("paipu_dir")
    parser.add_argument("--player-name", default="Levey")
    parser.add_argument("--uuid")
    parser.add_argument("--max-record-index", type=int)
    parser.add_argument(
        "--suggestion-lookback",
        type=int,
        default=3,
        help="Only build suggestions in this many records before each comparable discard.",
    )
    parser.add_argument("--summary-json", help="Optional path to write aggregate summary as JSON.")
    parser.add_argument("--summary-only", action="store_true", help="Only print the aggregate summary.")
    parser.add_argument("--progress", action="store_true", help="Print per-file progress to stderr.")
    args = parser.parse_args()

    aligned_dir = Path(args.aligned_dir)
    paipu_dir = Path(args.paipu_dir)
    results = []
    missing_paipu = []
    for aligned_path in sorted(aligned_dir.glob("*.aligned.json")):
        uuid = aligned_path.name.replace(".aligned.json", "")
        if args.uuid and uuid != args.uuid:
            continue
        if args.progress:
            print(f"[analyze] {uuid}", file=sys.stderr, flush=True)
        paipu_path = paipu_dir / aligned_path.name.replace(".aligned.json", ".json")
        if not paipu_path.exists():
            missing_paipu.append(uuid)
            continue
        result = compare_one(
            aligned_path,
            paipu_path,
            args.player_name,
            args.max_record_index,
            args.suggestion_lookback,
        )
        results.append(result)
        if not args.summary_only:
            print(json.dumps(result, ensure_ascii=False, indent=2))

    if results:
        total = sum(item["discard_matched"] for item in results)
        exact = sum(item["discard_exact"] for item in results)
        top3 = sum(item["discard_top3"] for item in results)
        actual_match = sum(item["discard_actual_match"] for item in results)
        seer_actual_match = sum(item["seer_actual_match"] for item in results)
        consensus_mismatch_count = sum(item["consensus_mismatch_count"] for item in results)
        mismatch_patterns = Counter()
        mismatch_tags = Counter()
        consensus_family_patterns = Counter()
        for item in results:
            accumulate_counter(mismatch_patterns, item.get("mismatch_patterns"))
            accumulate_counter(mismatch_tags, item.get("mismatch_tags"))
            accumulate_consensus_family_patterns(consensus_family_patterns, item.get("consensus_family_patterns"))
        summary = {
            "files": len(results),
            "missing_paipu_count": len(missing_paipu),
            "missing_paipu": missing_paipu[:20],
            "discard_matched": total,
            "discard_exact": exact,
            "discard_exact_rate": round(exact / total, 3) if total else None,
            "discard_top3": top3,
            "discard_top3_rate": round(top3 / total, 3) if total else None,
            "discard_actual_match": actual_match,
            "discard_actual_match_rate": round(actual_match / total, 3) if total else None,
            "seer_actual_match": seer_actual_match,
            "seer_actual_match_rate": round(seer_actual_match / total, 3) if total else None,
            "consensus_mismatch_count": consensus_mismatch_count,
            "mismatch_patterns": mismatch_patterns.most_common(),
            "mismatch_tags": mismatch_tags.most_common(10),
            "consensus_family_patterns": consensus_family_patterns.most_common(),
        }
        print("")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if args.summary_json:
            target = Path(args.summary_json)
            target.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif missing_paipu:
        summary = {
            "files": 0,
            "missing_paipu_count": len(missing_paipu),
            "missing_paipu": missing_paipu[:20],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if args.summary_json:
            target = Path(args.summary_json)
            target.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
