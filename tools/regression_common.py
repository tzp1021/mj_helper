#!/usr/bin/env python3

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
    state.open_melds = payload.get("open_melds", 0)
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
    state.current_scores = list(payload.get("current_scores") or [25000, 25000, 25000, 25000])
    state.left_tile_count = payload.get("left_tile_count")
    state.chang = payload.get("chang")
    state.ju = payload.get("ju")
    return state


def print_assert(label, ok, detail):
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {label}: {detail}")
    return 0 if ok else 1
