#!/usr/bin/env python3
import json
from pathlib import Path


DEFAULT_DATASETS = [
    (
        "/Users/bigo/code/mj/data/archive/tenhou_mjlog3_fast_merged.normalized.jsonl",
        "/Users/bigo/code/mj/data/archive/tenhou_mjlog3_refine_compare.json",
    ),
    (
        "/Users/bigo/code/mj/data/archive/tenhou_mjlog4_fast.jsonl",
        "/Users/bigo/code/mj/data/archive/tenhou_mjlog4_refine_compare.json",
    ),
    (
        "/Users/bigo/code/mj/data/archive/tenhou_mjlog5_fast.normalized.jsonl",
        "/Users/bigo/code/mj/data/archive/tenhou_mjlog5_refine_compare.json",
    ),
    (
        "/Users/bigo/code/mj/data/archive/tenhou_mjlog6_fast.normalized.jsonl",
        "/Users/bigo/code/mj/data/archive/tenhou_mjlog6_refine_compare.json",
    ),
    (
        "/Users/bigo/code/mj/data/archive/tenhou_mjlog7_fast.normalized.jsonl",
        "/Users/bigo/code/mj/data/archive/tenhou_mjlog7_refine_compare.json",
    ),
    (
        "/Users/bigo/code/mj/data/archive/tenhou_new_fast_merged.jsonl",
        "/Users/bigo/code/mj/data/archive/tenhou_new_refine_compare.json",
    ),
]


def load_jsonl_index(path, target_keys=None):
    index = {}
    target_keys = set(target_keys or [])
    use_filter = bool(target_keys)
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            key = (row["source_file"], row["index"])
            if use_filter and key not in target_keys:
                continue
            index[key] = row["snapshot"]
    return index


def normalize_tile(tile):
    if tile and tile[0] == "0" and tile[1] in "mps":
        return "5" + tile[1]
    return tile


def tile_to_index(tile):
    tile = normalize_tile(tile)
    number = int(tile[0])
    suit = tile[1]
    base = {"m": 0, "p": 9, "s": 18, "z": 27}[suit]
    return base + number - 1


def hand_to_counts(tiles):
    counts = [0] * 34
    for tile in tiles:
        counts[tile_to_index(tile)] += 1
    return counts


def hand_context_features(hand_tiles, tile):
    normalized = normalize_tile(tile)
    suit = normalized[1]
    number = int(normalized[0]) if suit != "z" else 0
    counts = hand_to_counts(hand_tiles)
    idx = tile_to_index(normalized)
    tile_count = counts[idx]
    left1 = right1 = left2 = right2 = 0
    if suit != "z":
        base = idx - (number - 1)
        if number >= 2:
            left1 = counts[base + number - 2]
        if number <= 8:
            right1 = counts[base + number]
        if number >= 3:
            left2 = counts[base + number - 3]
        if number <= 7:
            right2 = counts[base + number + 1]
    adjacent_count = left1 + right1
    gap_count = left2 + right2
    connected_score = adjacent_count + gap_count * 0.5
    isolated_cut = 1.0 if suit != "z" and tile_count == 1 and adjacent_count == 0 and gap_count == 0 else 0.0
    return {
        "tile_count_n": round(min(tile_count, 4) / 4.0, 4),
        "pair_source": 1.0 if tile_count >= 2 else 0.0,
        "triplet_source": 1.0 if tile_count >= 3 else 0.0,
        "singleton_cut": 1.0 if tile_count == 1 else 0.0,
        "breaks_head_candidate": 1.0 if tile_count >= 2 else 0.0,
        "adjacent_count_n": round(min(adjacent_count, 4) / 4.0, 4),
        "gap_count_n": round(min(gap_count, 4) / 4.0, 4),
        "connected_score_n": round(min(connected_score, 6.0) / 6.0, 4),
        "two_sided_support": 1.0 if left1 > 0 and right1 > 0 else 0.0,
        "flex_side_cut": 1.0 if tile_count == 1 and connected_score >= 1.5 else 0.0,
        "isolated_cut": isolated_cut,
    }


def candidate_features(snapshot, cand):
    tile = cand["tile"]
    normalized = normalize_tile(tile)
    suit = tile[1]
    number = int(normalized[0]) if suit != "z" else 0
    danger = float(cand.get("danger", 0.0) or 0.0)
    max_danger = float(cand.get("max_danger", 0.0) or 0.0)
    future_ukeire = float(cand.get("future_ukeire", 0.0) or 0.0)
    improvement_ukeire = float(cand.get("improvement_ukeire", 0.0) or 0.0)
    advance_ukeire = float(cand.get("advance_ukeire", 0.0) or 0.0)
    hand_value = float(cand.get("hand_value", 0.0) or 0.0)
    route_score = float(cand.get("route_score", 0.0) or 0.0)
    route_commitment = float(cand.get("route_commitment", 0.0) or 0.0)
    mode_score = float(cand.get("mode_score", 0.0) or 0.0)
    ukeire = float(cand.get("ukeire", 0.0) or 0.0)
    safe_tile_keep_count = float(cand.get("safe_tile_keep_count", 0.0) or 0.0)
    breaks_all_safety = 1.0 if cand.get("breaks_all_safety") else 0.0
    next_safe_exit = float(cand.get("next_safe_exit_count", 0.0) or 0.0)
    next_low_danger_exit = float(cand.get("next_low_danger_exit_count", 0.0) or 0.0)
    same_safety_band_exit = float(cand.get("same_safety_band_exit_count", 0.0) or 0.0)
    capped_advance_n = float(cand.get("capped_advance_n", 0.0) or 0.0)
    capped_improve_n = float(cand.get("capped_improve_n", 0.0) or 0.0)
    capped_future_n = float(cand.get("capped_future_n", 0.0) or 0.0)
    lead_residual_n = float(cand.get("lead_protect_residual_n", 0.0) or 0.0)
    comeback_residual_n = float(cand.get("comeback_residual_n", 0.0) or 0.0)
    route_retention_score = float(cand.get("route_retention_score", 0.0) or 0.0)
    mode = snapshot.get("push_fold")
    goal = snapshot.get("hand_goal")

    is_honor = 1.0 if suit == "z" else 0.0
    is_terminal = 1.0 if suit != "z" and number in (1, 9) else 0.0
    is_edge = 1.0 if suit != "z" and number in (2, 8) else 0.0
    is_center = 1.0 if suit != "z" and number in (4, 5, 6) else 0.0

    feats = {
        "mode_score_n": round(mode_score / 100.0, 4),
        "ukeire_n": round(ukeire / 40.0, 4),
        "advance_n": round(advance_ukeire / 40.0, 4),
        "improve_n": round(improvement_ukeire / 30.0, 4),
        "future_n": round(future_ukeire / 25.0, 4),
        "value_n": round(hand_value / 12.0, 4),
        "danger_n": round(danger / 6.0, 4),
        "max_danger_n": round(max_danger / 4.0, 4),
        "route_n": round(route_score / 5.0, 4),
        "route_commitment_n": round(route_commitment / 5.0, 4),
        "safe_keep_n": round(safe_tile_keep_count / 4.0, 4),
        "breaks_all_safety": breaks_all_safety,
        "next_safe_exit_n": round(min(next_safe_exit, 4.0) / 4.0, 4),
        "next_low_danger_exit_n": round(min(next_low_danger_exit, 6.0) / 6.0, 4),
        "same_safety_band_exit_n": round(min(same_safety_band_exit, 6.0) / 6.0, 4),
        "capped_advance_n": capped_advance_n,
        "capped_improve_n": capped_improve_n,
        "capped_future_n": capped_future_n,
        "lead_protect_residual_n": lead_residual_n,
        "comeback_residual_n": comeback_residual_n,
        "route_retention_score": round(route_retention_score / 5.0, 4),
        "yakuhai_retained": 1.0 if cand.get("yakuhai_retained") else 0.0,
        "yakuhai_pair_retained": 1.0 if cand.get("yakuhai_pair_retained") else 0.0,
        "tanyao_retained": 1.0 if cand.get("tanyao_retained") else 0.0,
        "flush_retained": 1.0 if cand.get("flush_retained") else 0.0,
        "dora_retained": 1.0 if cand.get("dora_retained") else 0.0,
        "dora_acceptance_retained": 1.0 if cand.get("dora_acceptance_retained") else 0.0,
        "honor_cut": is_honor,
        "terminal_cut": is_terminal,
        "edge_cut": is_edge,
        "center_cut": is_center,
        "danger_x_all_last": round(danger / 6.0, 4),
        "future_x_all_last": round(future_ukeire / 25.0, 4),
    }
    feats.update(hand_context_features(snapshot.get("hand") or [], tile))
    if mode == "fold":
        feats["danger_x_fold"] = feats["danger_n"]
        feats["max_danger_x_fold"] = feats["max_danger_n"]
        feats["honor_x_fold"] = is_honor
        feats["terminal_x_fold"] = is_terminal
        feats["safe_keep_x_fold"] = feats["safe_keep_n"]
        feats["connected_x_fold"] = feats["connected_score_n"]
        feats["next_safe_x_fold"] = feats["next_safe_exit_n"]
        feats["capped_future_x_fold"] = feats["capped_future_n"]
    if mode == "neutral":
        feats["future_x_neutral"] = feats["future_n"]
        feats["improve_x_neutral"] = feats["improve_n"]
        if goal == "速度优先":
            feats["future_x_neutral_speed"] = feats["future_n"]
            feats["improve_x_neutral_speed"] = feats["improve_n"]
            feats["connected_x_neutral_speed"] = feats["connected_score_n"]
            feats["two_sided_x_neutral_speed"] = feats["two_sided_support"]
            feats["shape_x_neutral_speed"] = feats["connected_score_n"]
        if goal == "稳定优先":
            feats["danger_x_neutral_stability"] = feats["danger_n"]
            feats["max_danger_x_neutral_stability"] = feats["max_danger_n"]
            feats["safe_keep_x_neutral_stability"] = feats["safe_keep_n"]
            feats["next_safe_x_neutral_stability"] = feats["next_safe_exit_n"]
            feats["lead_residual_x_neutral_stability"] = feats["lead_protect_residual_n"]
            feats["pair_x_neutral_stability"] = feats["pair_source"]
            feats["connected_x_neutral_stability"] = feats["connected_score_n"]
    if mode == "push":
        feats["future_x_push"] = feats["future_n"]
        if goal == "打点优先":
            feats["route_x_push_value"] = feats["route_n"]
            feats["value_x_push_value"] = feats["value_n"]
            feats["route_retention_x_push_value"] = feats["route_retention_score"]
            feats["comeback_residual_x_push_value"] = feats["comeback_residual_n"]
            feats["pair_x_push_value"] = feats["pair_source"]
            feats["connected_x_push_value"] = feats["connected_score_n"]
    return feats


def subtract_features(left, right):
    keys = set(left) | set(right)
    return {key: float(left.get(key, 0.0)) - float(right.get(key, 0.0)) for key in keys}


def prelim_compare_rows(compare_rows):
    for row in compare_rows:
        if row.get("same_recommendation", True):
            continue
        if row.get("fast_push_fold") != row.get("refined_push_fold"):
            continue
        if row.get("fast_hand_goal") != row.get("refined_hand_goal"):
            continue
        tags = list(row.get("priority_tags") or [])
        if not ({"very_close", "close"} & set(tags)):
            continue
        yield row


def iter_eligible_rows(datasets):
    for fast_path, compare_path in datasets:
        compare = json.loads(Path(compare_path).read_text(encoding="utf-8"))
        compare_rows = list(prelim_compare_rows(compare.get("rows", [])))
        target_keys = {(row["source_file"], row["index"]) for row in compare_rows}
        fast_index = load_jsonl_index(fast_path, target_keys=target_keys)
        dataset_name = Path(compare_path).stem
        for row in compare_rows:
            tags = list(row.get("priority_tags") or [])
            snap = fast_index.get((row["source_file"], row["index"]))
            if not snap or not snap.get("is_all_last") or snap.get("place") not in (1, 4):
                continue
            candidates = {cand["tile"]: cand for cand in snap.get("candidates", [])}
            fast_tile = row.get("fast_recommendation")
            refined_tile = row.get("refined_recommendation")
            if fast_tile not in candidates or refined_tile not in candidates:
                continue
            fast_cand = candidates[fast_tile]
            refined_cand = candidates[refined_tile]
            fast_feats = candidate_features(snap, fast_cand)
            refined_feats = candidate_features(snap, refined_cand)
            yield {
                "dataset": dataset_name,
                "fast_jsonl": fast_path,
                "compare_json": compare_path,
                "source_file": row["source_file"],
                "index": row["index"],
                "round": row.get("round") or snap.get("round"),
                "trigger": row.get("trigger") or snap.get("trigger"),
                "priority_tags": tags,
                "push_fold": row.get("fast_push_fold"),
                "hand_goal": row.get("fast_hand_goal"),
                "place": snap.get("place"),
                "phase": snap.get("phase"),
                "pressure": snap.get("pressure"),
                "confidence": snap.get("confidence"),
                "fast_tile": fast_tile,
                "refined_tile": refined_tile,
                "fast_tile_display": row.get("fast_recommendation_display"),
                "refined_tile_display": row.get("refined_recommendation_display"),
                "fast_features": fast_feats,
                "refined_features": refined_feats,
                "feature_diff": subtract_features(refined_feats, fast_feats),
            }


def build_examples(datasets):
    examples = []
    stats = {"rows": 0, "eligible_rows": 0, "pairwise_examples": 0}
    for fast_path, compare_path in datasets:
        compare = json.loads(Path(compare_path).read_text(encoding="utf-8"))
        stats["rows"] += len(compare.get("rows", []))
    for item in iter_eligible_rows(datasets):
        diff = item["feature_diff"]
        examples.append((diff, 1))
        examples.append(({key: -value for key, value in diff.items()}, -1))
        stats["eligible_rows"] += 1
    stats["pairwise_examples"] = len(examples)
    return examples, stats
