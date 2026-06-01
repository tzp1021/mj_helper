#!/usr/bin/env python3
"""Print a sanitized offline demo recommendation.

This script does not connect to Mahjong Soul or read private replay data. It
builds one representative in-memory game state and asks the live helper for the
same suggestion text used by the realtime path.
"""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from majsoul_live_helper import LiveGameState  # noqa: E402


def build_demo_state():
    state = LiveGameState()
    state.self_seat = 0
    state.seat_names = {
        0: "you",
        1: "shimocha",
        2: "toimen",
        3: "kamicha",
    }
    state.chang = 0
    state.ju = 2
    state.ben = 1
    state.round_label = "东3局1本场"
    state.left_tile_count = 36
    state.current_scores = [26300, 30100, 21900, 21700]
    state.dora_indicators = ["4p"]
    state.hand = [
        "2m",
        "3m",
        "4m",
        "5m",
        "6m",
        "7m",
        "2p",
        "3p",
        "4p",
        "5p",
        "6p",
        "7p",
        "8p",
        "8p",
    ]
    state.hand_seeded = True

    state.riichi_seats = {1}
    state.riichi_event_index = {1: 6}
    state.discards_by_seat = {
        1: ["1z", "4z", "7z"],
        2: ["9m", "1p", "9s"],
        3: ["1m", "9p", "2z"],
    }
    state.discard_meta_by_seat = {
        seat: [
            {"tile": tile, "event_index": index, "moqie": False, "is_liqi": seat == 1 and index == 2}
            for index, tile in enumerate(tiles)
        ]
        for seat, tiles in state.discards_by_seat.items()
    }
    return state


def main():
    state = build_demo_state()
    print("Mahjong Soul Live Helper demo")
    print("=" * 32)
    print(state.build_suggestion("离线模拟摸牌"))


if __name__ == "__main__":
    main()
