#!/usr/bin/env python3
import argparse
import json
from collections import Counter
from pathlib import Path

from majsoul_live_helper import parse_paipu_actions


def load_manifest(path):
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    return {row["uuid"]: row for row in rows or [] if row.get("uuid")}


def seer_recommend_seat(rec):
    seat = rec.get("seat")
    if seat is None:
        return 0
    return seat


def seer_action_to_tile(action):
    if 111 <= action <= 119:
        return f"{action - 110}m"
    if 121 <= action <= 129:
        return f"{action - 120}p"
    if 131 <= action <= 139:
        return f"{action - 130}s"
    if 141 <= action <= 147:
        return f"{action - 140}z"
    return None


def compare_one(paipu_path, seer_path, manifest_row, player_name):
    self_seat = (manifest_row.get("players") or []).index(player_name)
    _, outputs = parse_paipu_actions(paipu_path, player_name=player_name)
    snapshot_map = {item["index"]: item for item in outputs}
    seer = json.loads(Path(seer_path).read_text(encoding="utf-8"))

    matched = []
    mismatches = []
    round_mismatches = Counter()
    ours_counter = Counter()
    seer_counter = Counter()
    tag_counter = Counter()

    for event in ((seer.get("res") or {}).get("report") or {}).get("events") or []:
        record_index = event.get("record_index")
        if record_index is None or record_index not in snapshot_map:
            continue
        recommend = None
        for candidate in event.get("recommends") or []:
            if seer_recommend_seat(candidate) == self_seat:
                recommend = candidate
                break
        if not recommend:
            continue
        predictions = recommend.get("predictions") or []
        if not predictions:
            continue
        seer_tile = seer_action_to_tile(predictions[0].get("action"))
        if not seer_tile:
            continue
        snap = snapshot_map[record_index]
        snapshot = snap.get("snapshot") or {}
        ours_tile = snapshot.get("rule_recommendation")
        if not ours_tile:
            continue
        round_name = snapshot.get("round") or "unknown"
        matched.append({
            "index": record_index,
            "round": round_name,
            "ours": ours_tile,
            "seer": seer_tile,
            "seer_predictions": predictions[:3],
            "suggestion": snap.get("suggestion", "").splitlines()[0],
            "tags": ((snapshot.get("candidates") or [{}])[0].get("risk_reward_tags") or []),
        })
        ours_counter[ours_tile] += 1
        seer_counter[seer_tile] += 1
        if ours_tile != seer_tile:
            round_mismatches[round_name] += 1
            for tag in matched[-1]["tags"]:
                tag_counter[tag] += 1
            mismatches.append(matched[-1])

    exact = sum(1 for item in matched if item["ours"] == item["seer"])
    top3_hits = 0
    for item in matched:
        predicted_tiles = [
            seer_action_to_tile(pred.get("action"))
            for pred in item["seer_predictions"]
        ]
        if item["ours"] in predicted_tiles:
            top3_hits += 1

    return {
        "uuid": manifest_row.get("uuid"),
        "self_seat": self_seat,
        "player_name": player_name,
        "matched_discard_events": len(matched),
        "exact_matches": exact,
        "exact_rate": round(exact / len(matched), 3) if matched else None,
        "top3_hits": top3_hits,
        "top3_rate": round(top3_hits / len(matched), 3) if matched else None,
        "ours_top_tiles": ours_counter.most_common(10),
        "seer_top_tiles": seer_counter.most_common(10),
        "round_mismatches": round_mismatches.most_common(),
        "mismatch_tags": tag_counter.most_common(),
        "sample_mismatches": mismatches[:20],
    }


def main():
    parser = argparse.ArgumentParser(description="Compare local recommendations with Majsoul Seer (MAKA) report.")
    parser.add_argument("paipu_dir", help="Directory containing paipu json and matching .seer.json files")
    parser.add_argument("--player-name", default="Levey", help="Target player nickname")
    parser.add_argument("--manifest", help="Optional manifest path")
    args = parser.parse_args()

    root = Path(args.paipu_dir)
    manifest_path = args.manifest or str(root / "manifest.json")
    manifest = load_manifest(manifest_path)

    all_results = []
    for seer_path in sorted(root.glob("*.seer.json")):
        uuid = seer_path.name.replace(".seer.json", "")
        paipu_path = root / f"{uuid}.json"
        if not paipu_path.exists() or uuid not in manifest:
            continue
        result = compare_one(str(paipu_path), str(seer_path), manifest[uuid], args.player_name)
        all_results.append(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    if all_results:
        total_matched = sum(item["matched_discard_events"] for item in all_results)
        total_exact = sum(item["exact_matches"] for item in all_results)
        total_top3 = sum(item["top3_hits"] for item in all_results)
        print("")
        print(json.dumps({
            "files": len(all_results),
            "matched_discard_events": total_matched,
            "exact_matches": total_exact,
            "exact_rate": round(total_exact / total_matched, 3) if total_matched else None,
            "top3_hits": total_top3,
            "top3_rate": round(total_top3 / total_matched, 3) if total_matched else None,
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
