#!/usr/bin/env python3

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from majsoul_live_helper import LiveGameState, tile_to_index


def build_state(payload):
    state = LiveGameState()
    state.self_seat = payload.get("self_seat", 0)
    state.hand_seeded = True
    state.hand = list(payload.get("hand") or [])
    state.dora_indicators = list(payload.get("dora_indicators") or [])
    state.visible_counts = [0] * 34
    for tile, count in (payload.get("visible_counts") or {}).items():
        state.visible_counts[tile_to_index(tile)] = count
    state.riichi_seats = set(payload.get("riichi_seats") or [])
    state.riichi_event_index = {
        int(seat): value for seat, value in (payload.get("riichi_event_index") or {}).items()
    }
    state.open_melds_by_seat = {
        int(seat): count for seat, count in (payload.get("open_melds_by_seat") or {}).items()
    }
    state.discards_by_seat = {
        int(seat): list(tiles) for seat, tiles in (payload.get("discards_by_seat") or {}).items()
    }
    state.discard_meta_by_seat = {
        int(seat): list(items) for seat, items in (payload.get("discard_meta_by_seat") or {}).items()
    }
    state.melds_by_seat = {
        int(seat): list(items) for seat, items in (payload.get("melds_by_seat") or {}).items()
    }
    state.seat_names = {0: "you", 1: "A", 2: "B", 3: "C"}
    return state


def check_expectation(scores, exp):
    op = exp["op"]
    left = scores[exp["left"]]
    if op == "gt":
        right = scores[exp["right"]]
        ok = left > right
        detail = f"{exp['left']}({left}) > {exp['right']}({right})"
        return ok, detail
    if op == "lt":
        right = scores[exp["right"]]
        ok = left < right
        detail = f"{exp['left']}({left}) < {exp['right']}({right})"
        return ok, detail
    if op == "eq":
        right = exp["right_value"]
        ok = abs(left - right) <= 1e-9
        detail = f"{exp['left']}({left}) == {right}"
        return ok, detail
    if op == "near_zero":
        ok = abs(left) <= 0.05
        detail = f"{exp['left']}({left}) ~= 0"
        return ok, detail
    raise ValueError(f"unsupported op: {op}")


def main():
    case_path = Path(__file__).with_name("danger_cases.json")
    cases = json.loads(case_path.read_text(encoding="utf-8"))
    failed = 0
    for case in cases:
        state = build_state(case["state"])
        seat = case["seat"]
        rows = []
        scores = {}
        for tile in case["tiles"]:
            score = state.seat_tile_danger(seat, tile)
            rows.append((tile, score))
            scores[tile] = score
        rows.sort(key=lambda item: item[1], reverse=True)
        print(f"[{case['name']}] {case['description']}")
        for tile, score in rows:
            print(f"  {tile}: {score}")
        expectations = case.get("expectations") or []
        if expectations:
            print("  checks:")
        for exp in expectations:
            ok, detail = check_expectation(scores, exp)
            status = "PASS" if ok else "FAIL"
            print(f"    [{status}] {detail}")
            if not ok:
                failed += 1
        print("")
    if failed:
        raise SystemExit(f"{failed} danger expectation(s) failed")
    print("All danger expectations passed.")


if __name__ == "__main__":
    main()
