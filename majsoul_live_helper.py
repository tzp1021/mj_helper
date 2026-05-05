#!/usr/bin/env python3
import argparse
import base64
import json
import time
from functools import lru_cache
from pathlib import Path

import parse_majsoul_har as pmh


TILE_ORDER = "mpsz"
SUIT_BASE = {"m": 0, "p": 9, "s": 18, "z": 27}
HONOR_TEXT = {
    "1z": "东",
    "2z": "南",
    "3z": "西",
    "4z": "北",
    "5z": "白",
    "6z": "发",
    "7z": "中",
}


def normalize_tile(tile):
    if tile and tile[0] == "0" and tile[1] in "mps":
        return "5" + tile[1]
    return tile


def display_tile(tile):
    return HONOR_TEXT.get(tile, tile)


def tile_sort_key(tile):
    normalized = normalize_tile(tile)
    suit = normalized[1]
    number = int(normalized[0])
    red_bias = 0 if tile[0] == "0" else 1
    return (TILE_ORDER.index(suit), number, red_bias)


def format_tiles(tiles):
    return " ".join(display_tile(tile) for tile in sorted(tiles, key=tile_sort_key))


def tile_to_index(tile):
    normalized = normalize_tile(tile)
    number = int(normalized[0])
    suit = normalized[1]
    if suit == "z":
        return SUIT_BASE[suit] + number - 1
    return SUIT_BASE[suit] + number - 1


def index_to_tile(index):
    if index < 9:
        return f"{index + 1}m"
    if index < 18:
        return f"{index - 8}p"
    if index < 27:
        return f"{index - 17}s"
    return f"{index - 26}z"


def hand_to_counts(tiles):
    counts = [0] * 34
    for tile in tiles:
        counts[tile_to_index(tile)] += 1
    return counts


def tiles_to_visible_counts(tiles):
    counts = [0] * 34
    for tile in tiles:
        counts[tile_to_index(tile)] += 1
    return counts


def counts_to_pretty_tiles(counts):
    tiles = []
    for index, count in enumerate(counts):
        tiles.extend(index_to_tile(index) for _ in range(count))
    return tiles


def next_dora(indicator):
    indicator = normalize_tile(indicator)
    number = int(indicator[0])
    suit = indicator[1]
    if suit in "mps":
        return f"{1 if number == 9 else number + 1}{suit}"
    order = [1, 2, 3, 4, 1, 5, 6, 7, 5]
    return f"{order[number - 1]}z"


@lru_cache(maxsize=None)
def max_melds_taatsu(counts_key):
    counts = list(counts_key)
    start = 0
    while start < 34 and counts[start] == 0:
        start += 1
    if start >= 34:
        return (0, 0)

    def better(left, right):
        return max(left, right, key=lambda item: (item[0] * 2 + item[1], item[0]))

    next_counts = counts[:]
    next_counts[start] -= 1
    best = max_melds_taatsu(tuple(next_counts))

    if counts[start] >= 3:
        next_counts = counts[:]
        next_counts[start] -= 3
        melds, taatsu = max_melds_taatsu(tuple(next_counts))
        best = better(best, (melds + 1, taatsu))

    if start < 27 and start % 9 <= 6 and counts[start + 1] and counts[start + 2]:
        next_counts = counts[:]
        next_counts[start] -= 1
        next_counts[start + 1] -= 1
        next_counts[start + 2] -= 1
        melds, taatsu = max_melds_taatsu(tuple(next_counts))
        best = better(best, (melds + 1, taatsu))

    if counts[start] >= 2:
        next_counts = counts[:]
        next_counts[start] -= 2
        melds, taatsu = max_melds_taatsu(tuple(next_counts))
        best = better(best, (melds, taatsu + 1))

    if start < 27 and start % 9 <= 7 and counts[start + 1]:
        next_counts = counts[:]
        next_counts[start] -= 1
        next_counts[start + 1] -= 1
        melds, taatsu = max_melds_taatsu(tuple(next_counts))
        best = better(best, (melds, taatsu + 1))

    if start < 27 and start % 9 <= 6 and counts[start + 2]:
        next_counts = counts[:]
        next_counts[start] -= 1
        next_counts[start + 2] -= 1
        melds, taatsu = max_melds_taatsu(tuple(next_counts))
        best = better(best, (melds, taatsu + 1))

    return best


def shanten_normal(counts, open_melds=0):
    best = 8

    melds, taatsu = max_melds_taatsu(tuple(counts))
    taatsu = min(taatsu, max(0, 4 - melds - open_melds))
    best = min(best, 8 - (melds + open_melds) * 2 - taatsu)

    for pair_index in range(34):
        if counts[pair_index] < 2:
            continue
        counts[pair_index] -= 2
        melds, taatsu = max_melds_taatsu(tuple(counts))
        taatsu = min(taatsu, max(0, 4 - melds - open_melds))
        best = min(best, 8 - (melds + open_melds) * 2 - taatsu - 1)
        counts[pair_index] += 2

    return best


def shanten_chiitoi(counts):
    pairs = sum(1 for count in counts if count >= 2)
    uniques = sum(1 for count in counts if count > 0)
    return 6 - pairs + max(0, 7 - uniques)


def shanten_kokushi(counts):
    terminals = [0, 8, 9, 17, 18, 26] + list(range(27, 34))
    unique = sum(1 for index in terminals if counts[index] > 0)
    pair = any(counts[index] >= 2 for index in terminals)
    return 13 - unique - (1 if pair else 0)


def total_shanten(counts, open_melds=0):
    normal = shanten_normal(counts[:], open_melds)
    if open_melds:
        return normal
    return min(normal, shanten_chiitoi(counts), shanten_kokushi(counts))


def ukeire_for_counts(counts, shanten_value, open_melds, visible_counts=None):
    total = 0
    improving = []
    for index in range(34):
        if counts[index] >= 4:
            continue
        counts[index] += 1
        candidate = total_shanten(counts, open_melds)
        counts[index] -= 1
        if candidate < shanten_value:
            remaining = 4 - counts[index]
            if visible_counts is not None:
                remaining = 4 - counts[index] - visible_counts[index]
            remaining = max(0, remaining)
            total += remaining
            improving.append(index_to_tile(index))
    return total, improving


def dora_set(indicators):
    return {next_dora(indicator) for indicator in indicators or []}


def format_waits(tiles):
    return "/".join(display_tile(tile) for tile in tiles)


def safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def wait_shape_score(waits):
    unique_waits = sorted({normalize_tile(tile) for tile in waits if tile}, key=tile_sort_key)
    if not unique_waits:
        return 0.0
    if any(tile[1] == "z" for tile in unique_waits):
        base = 0.65 if len(unique_waits) == 1 else 0.95
    else:
        numbers = sorted(int(tile[0]) for tile in unique_waits)
        if len(unique_waits) >= 3:
            base = 1.8
        elif len(unique_waits) == 2:
            gap = numbers[1] - numbers[0]
            if gap == 1:
                base = 1.45
            elif gap == 2:
                base = 1.2
            else:
                base = 1.0
        else:
            base = 0.75
        if len(unique_waits) == 1:
            number = numbers[0]
            if number in (1, 9):
                base -= 0.2
            elif number in (2, 8):
                base -= 0.1
            elif number in (4, 5, 6):
                base += 0.1
    return round(base, 2)


def is_honor_index(index):
    return index >= 27


def is_terminal_or_honor_index(index):
    return index >= 27 or index % 9 in (0, 8)


def tile_neighbors(index):
    if index >= 27:
        return []
    suit_offset = (index // 9) * 9
    number = index % 9
    neighbors = []
    if number - 2 >= 0:
        neighbors.append(suit_offset + number - 2)
    if number - 1 >= 0:
        neighbors.append(suit_offset + number - 1)
    if number + 1 <= 8:
        neighbors.append(suit_offset + number + 1)
    if number + 2 <= 8:
        neighbors.append(suit_offset + number + 2)
    return neighbors


def isolated_tile_score(counts, index):
    count = counts[index]
    if count <= 0:
        return 0.0
    if count >= 2:
        return 0.0
    if is_honor_index(index):
        return 1.0
    for neighbor in tile_neighbors(index):
        if counts[neighbor]:
            return 0.0
    return 0.6 if is_terminal_or_honor_index(index) else 0.35


@lru_cache(maxsize=20000)
def _hand_value_score_cached(counts_key, indicator_key, seat_wind, round_wind, open_melds):
    counts = list(counts_key)
    actual_dora = dora_set(indicator_key or [])
    value_honors = {seat_wind, round_wind, "5z", "6z", "7z"} - {None}
    score = 0.0
    total_tiles = sum(counts)
    simple_tiles = 0
    suit_counts = [sum(counts[0:9]), sum(counts[9:18]), sum(counts[18:27])]
    pair_count = 0
    value_honor_count = 0

    for index, count in enumerate(counts):
        if not count:
            continue
        tile = index_to_tile(index)
        if tile in actual_dora:
            score += count * 1.8
        if count >= 2:
            pair_count += 1
        if is_honor_index(index):
            if tile in value_honors:
                value_honor_count += count
                if count == 1:
                    score += 1.25
                elif count == 2:
                    score += 2.9
                else:
                    score += 2.9 + (count - 2) * 1.15
            elif count == 1:
                score -= 0.35
            else:
                score += 0.35 * count
            continue

        number = index % 9 + 1
        if 2 <= number <= 8:
            simple_tiles += count
            score += count * 0.15
        else:
            score -= count * 0.05
        if number in (4, 5, 6):
            score += count * 0.12
        elif number in (3, 7):
            score += count * 0.05
        score -= isolated_tile_score(counts, index) * 0.35

    terminal_honor_tiles = total_tiles - simple_tiles
    honor_tiles = sum(counts[27:])
    if honor_tiles == 0 and terminal_honor_tiles <= 4:
        score += 1.1
    elif honor_tiles <= 1 and terminal_honor_tiles <= 6:
        score += 0.5

    dominant_suit = max(suit_counts) if suit_counts else 0
    if dominant_suit >= 8:
        score += (dominant_suit - 7) * 0.65
    elif dominant_suit >= 7:
        score += 0.55
    elif dominant_suit >= 6:
        score += 0.35

    if open_melds == 0 and pair_count >= 4:
        score += 1.15
    elif open_melds == 0 and pair_count >= 3:
        score += 0.5
    if open_melds == 0 and value_honor_count >= 2 and pair_count >= 2:
        score += 0.55
    if open_melds == 0 and value_honor_count >= 3 and honor_tiles >= 4:
        score += 0.45
    if open_melds == 0 and value_honor_count >= 3 and honor_tiles >= 5:
        score += 0.3
    if open_melds == 0 and dominant_suit >= 7 and honor_tiles <= 2:
        score += 0.4

    return round(score, 2)


def hand_value_score(counts, indicators=None, seat_wind=None, round_wind=None, open_melds=0):
    return _hand_value_score_cached(
        tuple(counts),
        tuple(indicators or []),
        seat_wind,
        round_wind,
        open_melds,
    )


@lru_cache(maxsize=50000)
def _shallow_best_hand_metrics_cached(counts_key, open_melds, visible_key, indicator_key, seat_wind, round_wind):
    counts = list(counts_key)
    visible_counts = list(visible_key) if visible_key is not None else None
    shanten_value = total_shanten(counts[:], open_melds)
    ukeire_count, _improving = ukeire_for_counts(counts, shanten_value, open_melds, visible_counts)
    value_score = hand_value_score(counts, indicator_key, seat_wind, round_wind, open_melds)
    quality_score = ukeire_count * 4.0 + value_score * 8.0
    return {
        "shanten": shanten_value,
        "ukeire": ukeire_count,
        "hand_value": value_score,
        "quality_score": quality_score,
    }


def shallow_best_hand_metrics(counts, open_melds=0, visible_counts=None, indicators=None, seat_wind=None, round_wind=None):
    return _shallow_best_hand_metrics_cached(
        tuple(counts),
        open_melds,
        tuple(visible_counts) if visible_counts is not None else None,
        tuple(indicators or []),
        seat_wind,
        round_wind,
    )


@lru_cache(maxsize=50000)
def _future_hand_progress_cached(counts_key, shanten_value, base_ukeire, open_melds, visible_key, indicator_key, seat_wind, round_wind):
    counts = list(counts_key)
    visible_counts = list(visible_key) if visible_key is not None else None
    indicators = list(indicator_key) if indicator_key is not None else None
    advance_total = 0
    improvement_total = 0
    future_ukeire = 0

    for index in range(34):
        if counts[index] >= 4:
            continue
        remaining = 4 - counts[index]
        if visible_counts is not None:
            remaining -= visible_counts[index]
        remaining = max(0, remaining)
        if remaining <= 0:
            continue

        counts[index] += 1
        best = None
        for discard_index in range(34):
            if counts[discard_index] <= 0:
                continue
            counts[discard_index] -= 1
            candidate = shallow_best_hand_metrics(
                counts,
                open_melds,
                visible_counts,
                indicators,
                seat_wind,
                round_wind,
            )
            counts[discard_index] += 1
            if (
                best is None
                or candidate["shanten"] < best["shanten"]
                or (
                    candidate["shanten"] == best["shanten"]
                    and candidate["quality_score"] > best["quality_score"]
                )
            ):
                best = candidate
        counts[index] -= 1
        if best is None:
            continue
        if best["shanten"] < shanten_value:
            advance_total += remaining
            future_ukeire += remaining * best["ukeire"]
        elif best["shanten"] == shanten_value and best["ukeire"] >= base_ukeire + 3:
            improvement_total += remaining
            future_ukeire += remaining * best["ukeire"]

    progress_total = advance_total + improvement_total
    future_ukeire_avg = round(future_ukeire / progress_total, 2) if progress_total else 0.0
    return advance_total, improvement_total, future_ukeire_avg


def future_hand_progress(counts, shanten_value, base_ukeire, open_melds=0, visible_counts=None, indicators=None, seat_wind=None, round_wind=None):
    return _future_hand_progress_cached(
        tuple(counts),
        shanten_value,
        base_ukeire,
        open_melds,
        tuple(visible_counts) if visible_counts is not None else None,
        tuple(indicators or []),
        seat_wind,
        round_wind,
    )


def recommend_discards(tiles, indicators, open_melds=0, visible_counts=None, seat_wind=None, round_wind=None):
    normalized_counts = hand_to_counts(tiles)
    unique_tiles = sorted(set(tiles), key=tile_sort_key)
    actual_dora = dora_set(indicators)
    value_honor_tiles = {seat_wind, round_wind, "5z", "6z", "7z"} - {None}
    value_honor_count_total = sum(
        normalized_counts[tile_to_index(tile)]
        for tile in value_honor_tiles
    )
    honor_count_total = sum(normalized_counts[27:])
    suit_counts = [sum(normalized_counts[0:9]), sum(normalized_counts[9:18]), sum(normalized_counts[18:27])]
    dominant_suit_index = max(range(3), key=lambda idx: suit_counts[idx]) if any(suit_counts) else None
    dominant_suit = "mps"[dominant_suit_index] if dominant_suit_index is not None else None
    options = []

    for tile in unique_tiles:
        counts = normalized_counts[:]
        discard_index = tile_to_index(tile)
        count_before_discard = normalized_counts[discard_index]
        counts[discard_index] -= 1
        shanten_value = total_shanten(counts, open_melds)
        ukeire_count, improving = ukeire_for_counts(counts, shanten_value, open_melds, visible_counts)
        hand_value = hand_value_score(counts, indicators, seat_wind, round_wind, open_melds)
        keep_value = 0
        normalized = normalize_tile(tile)
        if normalized in actual_dora:
            keep_value += 2.4
        if tile[0] == "0":
            keep_value += 1.2
        if normalized in value_honor_tiles:
            keep_value += 1.35 if count_before_discard == 1 else 2.2
        if normalized[1] == "z":
            if count_before_discard >= 2:
                keep_value += 0.45
            else:
                keep_value -= 0.1
                if (
                    normalized not in value_honor_tiles
                    and open_melds == 0
                    and value_honor_count_total >= 3
                    and honor_count_total >= 4
                ):
                    keep_value += 0.9
        else:
            number = int(normalized[0])
            if dominant_suit and normalized[1] == dominant_suit and suit_counts[dominant_suit_index] >= 7:
                keep_value += 0.35
                if number in (1, 9):
                    keep_value += 0.2
            elif dominant_suit and normalized[1] == dominant_suit and suit_counts[dominant_suit_index] >= 6:
                keep_value += 0.15
            if count_before_discard >= 2 and number in (1, 9):
                keep_value += 0.15
            if count_before_discard == 1 and isolated_tile_score(normalized_counts, discard_index) >= 0.6:
                keep_value -= 0.35
                if number in (1, 9):
                    keep_value -= 0.1

        options.append({
            "tile": tile,
            "shanten": shanten_value,
            "ukeire": ukeire_count,
            "advance_ukeire": 0,
            "improvement_ukeire": 0,
            "future_ukeire": 0.0,
            "hand_value": hand_value,
            "base_score": round(
                ukeire_count * 4.0
                + hand_value * 8.0
                - keep_value * 6.0,
                2,
            ),
            "efficiency_score": 0.0,
            "improving": improving,
            "danger_penalty": keep_value,
            "counts_after_discard": counts,
        })

    options.sort(
        key=lambda item: (
            item["shanten"],
            -item["base_score"],
            -item["ukeire"],
            item["danger_penalty"],
            tile_sort_key(item["tile"]),
        )
    )

    best_shanten = options[0]["shanten"] if options else None
    deep_candidates = []
    for item in options:
        if item["shanten"] != best_shanten:
            continue
        if len(deep_candidates) < 6:
            deep_candidates.append(item)
            continue
        if item["base_score"] >= deep_candidates[-1]["base_score"] - 10:
            deep_candidates.append(item)
        else:
            break

    for item in options:
        if item in deep_candidates:
            advance_ukeire, improvement_ukeire, future_ukeire = future_hand_progress(
                item["counts_after_discard"],
                item["shanten"],
                item["ukeire"],
                open_melds,
                visible_counts,
                indicators,
                seat_wind,
                round_wind,
            )
        else:
            advance_ukeire, improvement_ukeire, future_ukeire = 0, 0, 0.0
        item["advance_ukeire"] = advance_ukeire
        item["improvement_ukeire"] = improvement_ukeire
        item["future_ukeire"] = future_ukeire
        item["efficiency_score"] = round(
            item["base_score"]
            + advance_ukeire * 2.3
            + improvement_ukeire * 1.1
            + future_ukeire * 0.35,
            2,
        )
        item.pop("counts_after_discard", None)

    options.sort(
        key=lambda item: (
            item["shanten"],
            -item["efficiency_score"],
            -item["ukeire"],
            item["danger_penalty"],
            tile_sort_key(item["tile"]),
        )
    )
    return options


def tile_suji_partners(tile):
    normalized = normalize_tile(tile)
    number = int(normalized[0])
    suit = normalized[1]
    if suit == "z":
        return []
    partners = []
    if number - 3 >= 1:
        partners.append(f"{number - 3}{suit}")
    if number + 3 <= 9:
        partners.append(f"{number + 3}{suit}")
    return partners


def operation_type_label(op_type):
    return {
        1: "discard",
        2: "chi",
        3: "peng",
        4: "minggang",
        5: "angang",
        6: "jiagang",
        7: "zimo",
        8: "ron",
        9: "hule",
    }.get(op_type, f"type{op_type}")


def action_call_type_label(call_type):
    return {
        0: "吃后",
        1: "碰后",
        2: "大明杠后",
    }.get(call_type, "鸣牌后")


def confidence_label(score):
    if score >= 0.8:
        return "高"
    if score >= 0.55:
        return "中"
    return "低"


class LiveGameState:
    def __init__(self):
        self.self_account_id = None
        self.self_seat = None
        self.player_lookup = {}
        self.seat_list = []
        self.seat_names = {}
        self.hand = []
        self.hand_seeded = False
        self.dora_indicators = []
        self.visible_counts = [0] * 34
        self.open_melds = 0
        self.open_melds_by_seat = {}
        self.melds_by_seat = {}
        self.discards_by_seat = {}
        self.discard_meta_by_seat = {}
        self.riichi_seats = set()
        self.riichi_event_index = {}
        self.current_scores = []
        self.left_tile_count = None
        self.chang = None
        self.ju = None
        self.ben = 0
        self.liqibang = 0
        self.round_label = None
        self.event_index = -1
        self.last_suggestion_key = None
        self.pending_requests = {}
        self.pending_self_call = None
        self.last_deal_seat = None
        self.last_discard_data = None
        self.last_action_name = None
        self.last_action_data = None
        self.last_decision_snapshot = None
        self.last_action_plan = None
        self.last_tenpai_analysis = None
        self.last_discard_policy_note = None

    def current_shanten(self):
        return total_shanten(hand_to_counts(self.hand), self.open_melds)

    def current_ukeire(self):
        counts = hand_to_counts(self.hand)
        shanten_value = total_shanten(counts[:], self.open_melds)
        return ukeire_for_counts(counts, shanten_value, self.open_melds, self.visible_counts)[0]

    def estimated_turn(self):
        if self.left_tile_count is None:
            return None
        return max(1, ((70 - self.left_tile_count) // 4) + 1)

    def phase_label(self):
        turn = self.estimated_turn()
        if turn is None:
            return None
        if turn <= 6:
            return "早巡"
        if turn <= 12:
            return "中巡"
        return "后巡"

    def dealer_seat(self):
        if self.ju is None:
            return None
        return self.ju % 4

    def round_wind(self):
        if self.chang is None:
            return None
        return {0: "1z", 1: "2z", 2: "3z", 3: "4z"}.get(self.chang)

    def round_wind_display(self):
        wind = self.round_wind()
        return display_tile(wind) if wind else None

    def seat_wind(self, seat=None):
        seat = self.self_seat if seat is None else seat
        dealer = self.dealer_seat()
        if seat is None or dealer is None:
            return None
        return f"{((seat - dealer) % 4) + 1}z"

    def seat_wind_display(self, seat=None):
        wind = self.seat_wind(seat)
        return display_tile(wind) if wind else None

    def is_dealer(self):
        dealer = self.dealer_seat()
        return dealer is not None and dealer == self.self_seat

    def round_stage_pressure(self):
        if self.chang is None or self.ju is None:
            return 0
        if self.chang >= 1 and self.ju >= 2:
            return 2
        if self.chang >= 1:
            return 1
        return 0

    def score_context(self):
        if self.self_seat is None or not self.current_scores:
            return None
        indexed = list(enumerate(self.current_scores))
        sorted_scores = sorted(indexed, key=lambda item: item[1], reverse=True)
        place = next((idx + 1 for idx, (seat, _score) in enumerate(sorted_scores) if seat == self.self_seat), None)
        self_score = self.current_scores[self.self_seat]
        top_score = sorted_scores[0][1]
        last_score = sorted_scores[-1][1]
        second_score = sorted_scores[1][1] if len(sorted_scores) >= 2 else None
        third_score = sorted_scores[2][1] if len(sorted_scores) >= 3 else None
        return {
            "place": place,
            "self_score": self_score,
            "top_gap": top_score - self_score,
            "last_gap": self_score - last_score,
            "second_gap": next((score - self_score for seat, score in sorted_scores if seat != self.self_seat), 0),
            "score_diff_from_1st": self_score - top_score,
            "score_diff_from_2nd": self_score - second_score if second_score is not None else None,
            "score_diff_from_3rd": self_score - third_score if third_score is not None else None,
        }

    def add_visible_tile(self, tile):
        if not tile:
            return
        self.visible_counts[tile_to_index(tile)] += 1

    def add_visible_tiles(self, tiles):
        for tile in tiles or []:
            self.add_visible_tile(tile)

    def aka_count(self):
        return sum(1 for tile in self.hand if tile and tile[0] == "0")

    def is_value_honor(self, tile):
        normalized = normalize_tile(tile)
        if not normalized or normalized[1] != "z":
            return False
        return normalized in {self.seat_wind(), self.round_wind(), "5z", "6z", "7z"}

    def effective_safe_tiles(self):
        if not self.riichi_seats:
            return []
        return [
            tile for tile in sorted(set(self.hand), key=tile_sort_key)
            if self.max_seat_danger(tile) <= 0.9
        ]

    def riichi_state(self):
        return {
            "self_riichi": self.self_seat in self.riichi_seats if self.self_seat is not None else False,
            "riichi_seats": sorted(self.riichi_seats),
            "riichi_seats_display": [self.seat_name(seat) for seat in sorted(self.riichi_seats)],
            "riichi_event_index": {str(seat): self.riichi_event_index.get(seat) for seat in sorted(self.riichi_seats)},
        }

    def threat_summary(self):
        return {
            "riichi_count": len(self.riichi_seats),
            "riichi_threats": [
                {
                    "seat": seat,
                    "name": self.seat_name(seat),
                    "discards": len(self.discards_by_seat.get(seat, [])),
                    "dealer": seat == self.dealer_seat(),
                    "weight": self.seat_threat_weight(seat),
                }
                for seat in sorted(self.riichi_seats)
            ],
            "open_threats": [
                {
                    "seat": seat,
                    "name": self.seat_name(seat),
                    "meld_count": count,
                    "dealer": seat == self.dealer_seat(),
                }
                for seat, count in sorted(self.open_melds_by_seat.items())
                if seat != self.self_seat and count >= 2
            ],
            "pressure": self.pressure_label(),
        }

    def is_all_last(self):
        if self.ju != 3 or self.chang is None:
            return False
        return self.chang in (0, 1)

    def normalized_meld_type(self, call_type):
        return {
            0: "chi",
            1: "peng",
            2: "minggang",
            3: "jiagang",
        }.get(call_type, "meld")

    def record_meld(self, seat, meld_type, tiles, froms=None):
        if seat is None:
            return
        self.melds_by_seat.setdefault(seat, []).append({
            "type": meld_type,
            "tiles": list(tiles or []),
            "tiles_display": [display_tile(tile) for tile in (tiles or [])],
            "froms": list(froms or []),
        })

    def seat_threat_weight(self, seat):
        if seat not in self.riichi_seats:
            return 0.0
        weight = 1.0
        if seat == self.dealer_seat():
            weight += 0.35
        open_count = self.open_melds_by_seat.get(seat, 0)
        if open_count >= 2:
            weight += 0.15
        riichi_at = self.riichi_event_index.get(seat)
        if riichi_at is not None:
            riichi_discards = len(self.discards_by_seat.get(seat, []))
            if riichi_discards <= 6:
                weight += 0.1
            elif riichi_discards >= 12:
                weight += 0.25
        return round(weight, 2)

    def seat_tile_danger(self, seat, tile):
        normalized = normalize_tile(tile)
        if seat not in self.riichi_seats:
            return 0.0
        river = self.discards_by_seat.get(seat, [])
        river_norm = {normalize_tile(t) for t in river}
        if normalized in river_norm:
            return 0.0

        danger = 0.0
        actual_dora = dora_set(self.dora_indicators)
        discard_meta = self.discard_meta_by_seat.get(seat, [])
        riichi_idx = self.riichi_event_index.get(seat)
        late_tiles = []
        if riichi_idx is not None and discard_meta:
            late_tiles = [
                normalize_tile(item["tile"])
                for item in discard_meta[-3:]
                if item.get("tile")
            ]

        if normalized[1] == "z":
            visible = self.visible_counts[tile_to_index(normalized)]
            if visible >= 3:
                danger += 0.25
            elif visible == 2:
                danger += 0.75
            else:
                danger += 1.55
            if normalized in {self.seat_wind(seat), self.round_wind(), "5z", "6z", "7z"}:
                danger += 0.35
            return round(max(0.0, danger) * self.seat_threat_weight(seat), 2)

        partners = tile_suji_partners(normalized)
        if partners and all(partner in river_norm for partner in partners):
            danger += 0.55
        elif partners and any(partner in river_norm for partner in partners):
            danger += 1.1
        else:
            danger += 2.15

        number = int(normalized[0])
        if number in (1, 9):
            danger -= 0.25
        elif number in (2, 8):
            danger += 0.05
        elif number in (3, 7):
            danger += 0.2
        elif number in (4, 5, 6):
            danger += 0.45

        visible = self.visible_counts[tile_to_index(normalized)]
        if visible >= 3:
            danger -= 0.55
        elif visible == 2:
            danger -= 0.25

        if normalized in late_tiles:
            danger -= 0.35
        elif partners and any(partner in late_tiles for partner in partners):
            danger -= 0.15

        if normalized in actual_dora:
            danger += 0.5
        return round(max(0.0, danger) * self.seat_threat_weight(seat), 2)

    def max_seat_danger(self, tile):
        if not self.riichi_seats:
            return 0.0
        return max(self.seat_tile_danger(seat, tile) for seat in self.riichi_seats)

    def tile_danger_score(self, tile):
        normalized = normalize_tile(tile)
        if not self.riichi_seats:
            return 0.0
        seat_scores = [self.seat_tile_danger(seat, normalized) for seat in self.riichi_seats]
        return max(0.0, round(sum(seat_scores), 1))

    def danger_label(self, score):
        if score <= 0.3:
            return "现物级"
        if score <= 0.9:
            return "较安全"
        if score <= 1.6:
            return "一般"
        if score <= 2.4:
            return "偏危险"
        return "危险"

    def defensive_pressure(self):
        pressure = 0
        pressure += len(self.riichi_seats) * 2
        pressure += sum(
            1
            for seat, count in self.open_melds_by_seat.items()
            if seat != self.self_seat and count >= 2
        )
        turn = self.estimated_turn()
        if turn and turn >= 12:
            pressure += 1
        if any(seat == self.dealer_seat() for seat in self.riichi_seats):
            pressure += 1
        if any(
            seat == self.dealer_seat() and count >= 2
            for seat, count in self.open_melds_by_seat.items()
            if seat != self.self_seat
        ):
            pressure += 1
        pressure += self.round_stage_pressure()
        return pressure

    def pressure_label(self):
        pressure = self.defensive_pressure()
        if pressure >= 5:
            return "很高"
        if pressure >= 3:
            return "较高"
        if pressure >= 1:
            return "一般"
        return "低"

    def evaluate_discard_options(self):
        options = recommend_discards(
            self.hand,
            self.dora_indicators,
            self.open_melds,
            self.visible_counts,
            self.seat_wind(),
            self.round_wind(),
        )
        options = self.annotate_discard_risk_patterns(options)
        if self.riichi_seats:
            pressure = self.defensive_pressure()
            tilt = self.strategic_tilt()
            options.sort(
                key=lambda item: (
                    item["shanten"],
                    self.tile_danger_score(item["tile"]) * self.risk_weight_for_option(item, pressure, tilt),
                    -item["efficiency_score"],
                    tile_sort_key(item["tile"]),
                )
            )
            options = self.apply_discard_safety_policy(options, pressure, tilt)
        return options

    def annotate_discard_risk_patterns(self, options):
        if not options:
            return options
        current_shanten = self.current_shanten()
        for item in options:
            tags = []
            danger = self.tile_danger_score(item["tile"]) if self.riichi_seats else 0.0
            max_danger = self.max_seat_danger(item["tile"]) if self.riichi_seats else 0.0
            if item["shanten"] <= current_shanten:
                if item["shanten"] == 0 and item["ukeire"] >= 6:
                    tags.append("高质量听牌")
                elif item["shanten"] == 1 and item.get("advance_ukeire", 0) >= 18:
                    tags.append("强一向听")
            if danger >= 2.4:
                tags.append("高总危险")
            if max_danger >= 1.8:
                tags.append("单家高危险")
            if item.get("hand_value", 0.0) >= 4.5:
                tags.append("高打点路线")
            item["risk_reward_tags"] = tags[:4]
        return options

    def discard_push_template(self, item):
        tags = set(item.get("risk_reward_tags", []))
        if "高总危险" in tags and "高质量听牌" in tags:
            return "high_risk_tenpai_push"
        if "高总危险" in tags and "强一向听" in tags:
            return "high_risk_1shanten_push"
        if "高总危险" in tags and "高打点路线" in tags:
            return "high_value_risky_push"
        return None

    def should_preserve_risky_discard(self, best, pressure, tilt, score_gap):
        tags = set(best.get("risk_reward_tags", []))
        max_danger = self.max_seat_danger(best["tile"]) if self.riichi_seats else 0.0
        score_ctx = self.score_context() or {}
        if max_danger >= 2.6:
            return None
        if self.is_all_last() and tilt == "保守":
            return None
        if self.is_all_last() and score_ctx.get("place") == 1:
            return None
        if "高打点路线" in tags and max_danger <= 2.2 and score_gap >= 5:
            return "value_route_keep"
        if tilt == "积极" and best["shanten"] == 0 and "高质量听牌" in tags and score_gap >= 8:
            return "tenpai_keep"
        if (
            self.is_all_last()
            and score_ctx.get("place") == 4
            and "高打点路线" in tags
            and best["shanten"] <= 1
            and score_gap >= 6
        ):
            return "all_last_value_keep"
        if (
            tilt == "积极"
            and self.is_dealer()
            and "高打点路线" in tags
            and ("强一向听" in tags or "高质量听牌" in tags)
            and score_gap >= 10
            and pressure <= 5
        ):
            return "dealer_value_keep"
        return None

    def discard_override_bucket(self, best, safer_alt, pressure, tilt, score_gap, reason):
        best_tags = set(best.get("risk_reward_tags", []))
        if reason == "high_pressure_safer_override":
            return "high_pressure_override"
        if best["shanten"] == 0 and "高质量听牌" in best_tags:
            return "tenpai_push_overridden"
        if "高打点路线" in best_tags and ("强一向听" in best_tags or score_gap >= 10):
            return "value_push_overridden"
        if tilt == "保守" or pressure >= 5:
            return "same_shanten_safer_override"
        return "neutral_safety_override"

    def risk_weight_for_option(self, item, pressure=None, tilt=None):
        pressure = self.defensive_pressure() if pressure is None else pressure
        tilt = self.strategic_tilt() if tilt is None else tilt
        weight = 2.4 if pressure >= 5 else 1.8 if pressure >= 3 else 1.0
        if item["shanten"] == 0:
            weight -= 0.75
        elif item["shanten"] == 1:
            weight -= 0.35
        if self.is_dealer():
            weight -= 0.1
        if tilt == "积极":
            weight -= 0.25
        elif tilt == "保守":
            weight += 0.3
        template = self.discard_push_template(item)
        if template == "high_risk_tenpai_push":
            if tilt == "积极":
                weight -= 0.25
        elif template == "high_risk_1shanten_push":
            if tilt != "积极":
                weight += 0.2
        elif template == "high_value_risky_push":
            if tilt == "保守":
                weight += 0.15
            elif tilt == "积极":
                weight -= 0.1
        return max(0.55, round(weight, 2))

    def apply_discard_safety_policy(self, options, pressure=None, tilt=None):
        if not options or not self.riichi_seats:
            self.last_discard_policy_note = None
            return options
        pressure = self.defensive_pressure() if pressure is None else pressure
        tilt = self.strategic_tilt() if tilt is None else tilt
        best = options[0]
        best_max_danger = self.max_seat_danger(best["tile"])
        if best["shanten"] == 0 and tilt == "积极":
            self.last_discard_policy_note = None
            return options
        if self.discard_push_template(best) == "high_risk_tenpai_push" and tilt == "积极":
            self.last_discard_policy_note = None
            return options

        same_shanten_alts = [
            item for item in options[1:]
            if item["shanten"] == best["shanten"]
            and self.max_seat_danger(item["tile"]) <= 1.0
        ]
        if not same_shanten_alts:
            self.last_discard_policy_note = None
            return options

        safer_alt = same_shanten_alts[0]
        score_gap = best["efficiency_score"] - safer_alt["efficiency_score"]
        preserve_reason = self.should_preserve_risky_discard(best, pressure, tilt, score_gap)
        if preserve_reason:
            self.last_discard_policy_note = {
                "reason": "preserve_risky_push",
                "preserve_reason": preserve_reason,
                "from_tile": best["tile"],
                "to_tile": safer_alt["tile"],
                "score_gap": round(score_gap, 2),
                "pressure": pressure,
                "tilt": tilt,
                "bucket": preserve_reason,
            }
            return options
        conservative = (
            tilt == "保守"
            or pressure >= 5
            or (
                self.is_all_last()
                and (self.score_context() or {}).get("place") == 1
            )
        )
        if best_max_danger >= 1.8 and conservative and score_gap <= 18:
            bucket = self.discard_override_bucket(
                best,
                safer_alt,
                pressure,
                tilt,
                score_gap,
                "same_shanten_safer_override",
            )
            self.last_discard_policy_note = {
                "reason": "same_shanten_safer_override",
                "from_tile": best["tile"],
                "to_tile": safer_alt["tile"],
                "score_gap": round(score_gap, 2),
                "pressure": pressure,
                "tilt": tilt,
                "bucket": bucket,
                "from_max_danger": round(best_max_danger, 2),
                "to_max_danger": round(self.max_seat_danger(safer_alt["tile"]), 2),
            }
            reordered = [safer_alt] + [item for item in options if item is not safer_alt]
            return reordered
        if best_max_danger >= 2.2 and pressure >= 4 and score_gap <= 10:
            bucket = self.discard_override_bucket(
                best,
                safer_alt,
                pressure,
                tilt,
                score_gap,
                "high_pressure_safer_override",
            )
            self.last_discard_policy_note = {
                "reason": "high_pressure_safer_override",
                "from_tile": best["tile"],
                "to_tile": safer_alt["tile"],
                "score_gap": round(score_gap, 2),
                "pressure": pressure,
                "tilt": tilt,
                "bucket": bucket,
                "from_max_danger": round(best_max_danger, 2),
                "to_max_danger": round(self.max_seat_danger(safer_alt["tile"]), 2),
            }
            reordered = [safer_alt] + [item for item in options if item is not safer_alt]
            return reordered
        self.last_discard_policy_note = None
        return options

    def recommendation_confidence(self, options):
        if not options:
            return 0.0
        best = options[0]
        second = options[1] if len(options) > 1 else None
        score = 0.45
        if second is None:
            score += 0.25
        else:
            if best["shanten"] < second["shanten"]:
                score += 0.3
            else:
                ukeire_gap = best["ukeire"] - second["ukeire"]
                if ukeire_gap >= 12:
                    score += 0.25
                elif ukeire_gap >= 6:
                    score += 0.15
                elif ukeire_gap >= 2:
                    score += 0.08
                else:
                    score -= 0.1

                if self.riichi_seats:
                    danger_gap = self.tile_danger_score(second["tile"]) - self.tile_danger_score(best["tile"])
                    if danger_gap >= 1.0:
                        score += 0.15
                    elif danger_gap <= 0.2:
                        score -= 0.05

        if self.defensive_pressure() >= 4 and best["shanten"] > 0:
            score -= 0.05
        return max(0.0, min(0.99, round(score, 2)))

    def discard_policy_note_text(self):
        note = self.last_discard_policy_note or {}
        if not note:
            return None
        from_tile = display_tile(note.get("from_tile")) if note.get("from_tile") else "?"
        to_tile = display_tile(note.get("to_tile")) if note.get("to_tile") else "?"
        if note.get("reason") == "preserve_risky_push":
            preserve_reason = note.get("preserve_reason")
            if preserve_reason == "all_last_value_keep":
                return f"策略提示: 终局落后时保留 {from_tile} 的高价值推进，不改成更安全的 {to_tile}。"
            if preserve_reason == "value_route_keep":
                return f"策略提示: 这手本身有较强打点路线，保留 {from_tile} 的进攻价值，不改切 {to_tile}。"
            if preserve_reason == "dealer_value_keep":
                return f"策略提示: 亲家进攻收益更高，这里保留 {from_tile} 的高收益路线，不改切 {to_tile}。"
            if preserve_reason == "tenpai_keep":
                return f"策略提示: 当前属于可接受风险的强听牌推进，保留 {from_tile}，不改切 {to_tile}。"
        if note.get("reason") == "same_shanten_safer_override":
            return f"策略提示: 同向听下为了降低放铳风险，改从 {from_tile} 调整为更安全的 {to_tile}。"
        if note.get("reason") == "high_pressure_safer_override":
            return f"策略提示: 场压过高时优先安全，改从 {from_tile} 调整为更安全的 {to_tile}。"
        return None

    def build_decision_snapshot(self, trigger, options):
        score_ctx = self.score_context()
        best = options[0] if options else None
        snapshot = {
            "round": self.round_label,
            "trigger": trigger,
            "round_wind": self.round_wind(),
            "round_wind_display": self.round_wind_display(),
            "seat_wind": self.seat_wind(),
            "seat_wind_display": self.seat_wind_display(),
            "hand": sorted(self.hand, key=tile_sort_key),
            "hand_display": [display_tile(tile) for tile in sorted(self.hand, key=tile_sort_key)],
            "dora_indicators": list(self.dora_indicators),
            "dora_display": [display_tile(tile) for tile in self.dora_indicators],
            "self_seat": self.self_seat,
            "dealer": self.is_dealer(),
            "turn_est": self.estimated_turn(),
            "phase": self.phase_label(),
            "place": score_ctx["place"] if score_ctx else None,
            "scores": list(self.current_scores),
            "score_diff_from_1st": score_ctx["score_diff_from_1st"] if score_ctx else None,
            "score_diff_from_2nd": score_ctx["score_diff_from_2nd"] if score_ctx else None,
            "score_diff_from_3rd": score_ctx["score_diff_from_3rd"] if score_ctx else None,
            "is_all_last": self.is_all_last(),
            "remaining_tiles_est": self.left_tile_count,
            "aka_count": self.aka_count(),
            "riichi_state": self.riichi_state(),
            "pressure": self.pressure_label(),
            "tilt": self.strategic_tilt(),
            "visible_counts": {index_to_tile(i): count for i, count in enumerate(self.visible_counts) if count},
            "effective_safe_tiles": self.effective_safe_tiles(),
            "effective_safe_tiles_display": [display_tile(tile) for tile in self.effective_safe_tiles()],
            "threat_summary": self.threat_summary(),
            "melds": {str(seat): self.melds_by_seat.get(seat, []) for seat in range(4)},
            "discards_all": {str(seat): list(self.discards_by_seat.get(seat, [])) for seat in range(4)},
            "discards_all_display": {
                str(seat): [display_tile(tile) for tile in self.discards_by_seat.get(seat, [])]
                for seat in range(4)
            },
            "candidates": [],
        }
        for item in options[:3]:
            snapshot["candidates"].append({
                "tile": item["tile"],
                "tile_display": display_tile(item["tile"]),
                "shanten": item["shanten"],
                "ukeire": item["ukeire"],
                "advance_ukeire": item.get("advance_ukeire"),
                "improvement_ukeire": item.get("improvement_ukeire"),
                "future_ukeire": item.get("future_ukeire"),
                "hand_value": item.get("hand_value"),
                "danger": self.tile_danger_score(item["tile"]) if self.riichi_seats else 0.0,
                "risk_reward_tags": item.get("risk_reward_tags", []),
                "seat_dangers": {
                    str(seat): self.seat_tile_danger(seat, item["tile"])
                    for seat in sorted(self.riichi_seats)
                } if self.riichi_seats else {},
                "improving": item["improving"][:10],
                "improving_display": [display_tile(tile) for tile in item["improving"][:10]],
            })
        if best:
            snapshot["rule_recommendation"] = best["tile"]
            snapshot["rule_recommendation_display"] = display_tile(best["tile"])
            snapshot["confidence"] = self.recommendation_confidence(options)
            snapshot["discard_policy_note"] = self.last_discard_policy_note
        return snapshot

    def strategic_tilt(self):
        score_ctx = self.score_context()
        if not score_ctx:
            return None
        aggressive = 0
        if self.is_dealer():
            aggressive += 1
        if score_ctx["place"] == 4:
            aggressive += 2
        elif score_ctx["place"] == 3 and score_ctx["top_gap"] > 8000:
            aggressive += 1
        if self.chang is not None and self.chang >= 1:
            aggressive += 1
        if score_ctx["place"] == 1 and score_ctx["last_gap"] > 8000:
            aggressive -= 1
        if self.is_all_last():
            if score_ctx["place"] == 4:
                aggressive += 2
            elif score_ctx["place"] == 3 and (score_ctx["score_diff_from_3rd"] or 0) < 0:
                aggressive += 1
            elif score_ctx["place"] == 2 and (score_ctx["score_diff_from_1st"] or 0) > -2000:
                aggressive += 1
            elif score_ctx["place"] == 1 and score_ctx["last_gap"] > 4000:
                aggressive -= 2
        if aggressive >= 3:
            return "积极"
        if aggressive <= -1:
            return "保守"
        return "均衡"

    def should_fold_strictly(self, best):
        if not self.riichi_seats:
            return False
        score_ctx = self.score_context() or {}
        safe_tiles = self.effective_safe_tiles()
        max_danger = self.max_seat_danger(best["tile"])
        if self.defensive_pressure() >= 5 and best["shanten"] > 0 and safe_tiles:
            return True
        if self.is_all_last() and score_ctx.get("place") == 1 and safe_tiles and best["shanten"] > 0:
            return True
        if best["shanten"] >= 2 and max_danger >= 1.8 and safe_tiles:
            return True
        return False

    def open_yaku_profile(self, counts, called_tile=None):
        score = 0.0
        tags = []
        value_tiles = {self.seat_wind(), self.round_wind(), "5z", "6z", "7z"} - {None}
        for tile in value_tiles:
            index = tile_to_index(tile)
            if counts[index] >= 2:
                score += 1.3
                tags.append(f"役牌对{display_tile(tile)}")
            elif counts[index] == 1:
                score += 0.35
        simple_count = sum(
            count for index, count in enumerate(counts)
            if count and not is_terminal_or_honor_index(index)
        )
        terminal_honor_count = sum(
            count for index, count in enumerate(counts)
            if count and is_terminal_or_honor_index(index)
        )
        if simple_count >= max(8, terminal_honor_count + 3):
            score += 1.1
            tags.append("断幺")
        suit_counts = [sum(counts[0:9]), sum(counts[9:18]), sum(counts[18:27])]
        dominant_suit = max(suit_counts) if suit_counts else 0
        if dominant_suit >= 8:
            score += 0.9
            tags.append("染手")
        elif dominant_suit >= 6:
            score += 0.35
            tags.append("一色寄り")
        if called_tile:
            normalized = normalize_tile(called_tile)
            if normalized in value_tiles:
                score += 1.0
                tags.append(f"鸣入役牌{display_tile(normalized)}")
            if normalized in dora_set(self.dora_indicators):
                score += 0.7
                tags.append("鸣入宝牌")
        return {
            "score": round(score, 2),
            "tags": tags[:4],
        }

    def open_yaku_potential(self, counts, called_tile=None):
        return self.open_yaku_profile(counts, called_tile)["score"]

    def call_breaks_safety(self, used_tiles, discard_tile):
        if not self.riichi_seats:
            return 0.0
        before_safe = len(self.effective_safe_tiles())
        consumed_safe = sum(1 for tile in used_tiles if self.max_seat_danger(tile) <= 0.9)
        discard_safe = 1 if discard_tile and self.max_seat_danger(discard_tile) <= 0.9 else 0
        after_safe = max(0, before_safe - consumed_safe - discard_safe)
        if before_safe >= 2 and after_safe == 0:
            return 1.4
        if before_safe >= 1 and after_safe == 0:
            return 0.9
        return 0.0

    def call_tenpai_bonus(self, candidate):
        bonus = 0.0
        if candidate["shanten"] == 0:
            bonus += candidate["ukeire"] * 0.55
            bonus += min(candidate.get("hand_value", 0.0), 6.0) * 0.45
        elif candidate["shanten"] == 1:
            bonus += candidate.get("advance_ukeire", 0) * 0.12
            bonus += candidate.get("future_ukeire", 0.0) * 0.08
        return round(bonus, 2)

    def call_rejection_template(self, candidate):
        breakdown = candidate.get("call_breakdown", {})
        danger_loss = breakdown.get("danger_loss", 0.0)
        yaku_gain = breakdown.get("yaku_gain", 0.0)
        tenpai_bonus = breakdown.get("tenpai_bonus", 0.0)
        if danger_loss >= 2.0:
            return "high_danger_loss"
        if danger_loss >= 1.2 and tenpai_bonus < 2.0:
            return "danger_over_speed"
        if yaku_gain < 4.0 and tenpai_bonus < 2.0:
            return "weak_value_path"
        if yaku_gain >= 4.0 and danger_loss >= 1.0:
            return "value_but_risky"
        return "borderline_recheck"

    def should_allow_same_shanten_call(self, candidate, op_type=None):
        breakdown = candidate.get("call_breakdown", {})
        yaku_score = candidate.get("yaku_profile", {}).get("score", 0.0)
        tags = set(candidate.get("yaku_profile", {}).get("tags", []))
        tanyao_flush_like = "断幺" in tags and any(tag in tags for tag in ("一色寄り", "染手"))
        value_honor_like = any(tag.startswith("役牌对") or tag.startswith("鸣入役牌") for tag in tags)
        if self.riichi_seats:
            if self.max_seat_danger(candidate["tile"]) >= 1.4:
                return False, "danger_block"
            if breakdown.get("danger_loss", 0.0) >= 1.8:
                return False, "danger_block"
            if (
                breakdown.get("tenpai_bonus", 0.0) >= 4.4
                and breakdown.get("danger_loss", 0.0) <= 1.0
                and candidate.get("call_score", 0.0) >= 9.2
            ):
                return True, "riichi_exception"
            return False, "riichi_block"
        if self.strategic_tilt() == "积极" and candidate.get("call_score", 0.0) >= 5.4 and yaku_score >= 1.6:
            return True, "aggressive_push"
        if (
            op_type == 2
            and tanyao_flush_like
            and breakdown.get("tenpai_bonus", 0.0) >= 2.8
            and breakdown.get("danger_loss", 0.0) <= 0.8
            and candidate.get("call_score", 0.0) >= 6.8
        ):
            return True, "chi_pattern_release"
        if (
            op_type == 3
            and value_honor_like
            and breakdown.get("tenpai_bonus", 0.0) >= 2.4
            and breakdown.get("danger_loss", 0.0) <= 0.8
            and candidate.get("call_score", 0.0) >= 6.6
        ):
            if breakdown.get("tenpai_bonus", 0.0) >= 3.2 and candidate.get("call_score", 0.0) >= 7.2:
                return True, "peng_tenpai_release"
            return True, "peng_pattern_release"
        if (
            candidate.get("call_score", 0.0) >= 6.6
            and breakdown.get("tenpai_bonus", 0.0) >= 2.4
            and breakdown.get("danger_loss", 0.0) <= 1.0
            and (tanyao_flush_like or value_honor_like)
        ):
            return True, "pattern_release"
        if (
            candidate.get("call_score", 0.0) >= 7.2
            and (
                breakdown.get("yaku_gain", 0.0) >= 4.4
                or breakdown.get("tenpai_bonus", 0.0) >= 2.4
            )
        ):
            return True, "route_push"
        return False, "default_block"

    def same_shanten_reject_reason(self, called_tile, label, candidate):
        template = self.call_rejection_template(candidate)
        if template == "high_danger_loss":
            return f"不建议 {label} {display_tile(called_tile)}，这手副露后的危险损失过大，明显不值得强行提速。"
        if template == "danger_over_speed":
            return f"不建议 {label} {display_tile(called_tile)}，当前风险明显高于提速收益，先保留门清和防守空间更稳。"
        if template == "weak_value_path":
            return f"不建议 {label} {display_tile(called_tile)}，鸣后役种和听牌质量都不够强，暂时不值得副露。"
        if template == "value_but_risky":
            return f"不建议 {label} {display_tile(called_tile)}，虽然有役种收益，但这手要付出的危险代价仍偏大。"
        return f"不建议 {label} {display_tile(called_tile)}，鸣后役种/打点或退路收益不够，先门清前进更稳。"

    def call_plan_score(self, candidate, current_shanten, current_ukeire, called_tile=None, used_tiles=None):
        used_tiles = used_tiles or []
        yaku_profile = self.open_yaku_profile(candidate["counts_after_call"], called_tile)
        breakdown = {
            "shanten_gain": (current_shanten - candidate["shanten"]) * 11.0,
            "ukeire_gain": max(0, candidate["ukeire"] - current_ukeire) * 0.6,
            "advance_gain": candidate.get("advance_ukeire", 0) * 0.18,
            "improvement_gain": candidate.get("improvement_ukeire", 0) * 0.08,
            "hand_value_gain": candidate.get("hand_value", 0.0) * 1.4,
            "yaku_gain": yaku_profile["score"] * 2.1,
            "tenpai_bonus": self.call_tenpai_bonus(candidate),
            "dora_call_bonus": 0.0,
            "safety_loss": 0.0,
            "danger_loss": 0.0,
        }
        if called_tile and normalize_tile(called_tile) in dora_set(self.dora_indicators):
            breakdown["dora_call_bonus"] = 1.0
        if self.riichi_seats:
            breakdown["safety_loss"] = self.call_breaks_safety(used_tiles, candidate["tile"]) * 2.0
            breakdown["danger_loss"] = self.max_seat_danger(candidate["tile"]) * (0.6 if candidate["shanten"] == 0 else 1.0)
        score = round(
            breakdown["shanten_gain"]
            + breakdown["ukeire_gain"]
            + breakdown["advance_gain"]
            + breakdown["improvement_gain"]
            + breakdown["hand_value_gain"]
            + breakdown["yaku_gain"]
            + breakdown["tenpai_bonus"]
            + breakdown["dora_call_bonus"]
            - breakdown["safety_loss"]
            - breakdown["danger_loss"],
            2,
        )
        breakdown = {key: round(value, 2) for key, value in breakdown.items()}
        return score, yaku_profile, breakdown

    def build_call_advice(self, op_type, combinations, called_tile):
        plan = self.build_call_plan(op_type, combinations, called_tile)
        return plan["reason"] if plan else "有可鸣牌操作，但当前还没有足够信息做稳妥建议。"

    def build_call_plan(self, op_type, combinations, called_tile):
        current_shanten = self.current_shanten()
        current_ukeire = self.current_ukeire()
        best = None

        for combo in combinations or []:
            used_tiles = combo.split("|") if combo else []
            remaining = list(self.hand)
            ok = True
            for tile in used_tiles:
                before = len(remaining)
                self._remove_one_from_list(remaining, tile)
                if len(remaining) == before:
                    ok = False
                    break
            if not ok:
                continue
            options = recommend_discards(
                remaining,
                self.dora_indicators,
                self.open_melds + 1,
                self.visible_counts,
                self.seat_wind(),
                self.round_wind(),
            )
            if not options:
                continue
            candidate = options[0].copy()
            candidate["combo"] = combo
            candidate["used_tiles"] = used_tiles
            candidate["counts_after_call"] = hand_to_counts(remaining)
            candidate["call_score"], candidate["yaku_profile"], candidate["call_breakdown"] = self.call_plan_score(
                candidate,
                current_shanten,
                current_ukeire,
                called_tile,
                used_tiles,
            )
            if (
                best is None
                or candidate["shanten"] < best["shanten"]
                or (
                    candidate["shanten"] == best["shanten"]
                    and candidate["call_score"] > best["call_score"]
                )
            ):
                best = candidate

        if op_type in (8, 9):
            return {
                "action": "hule",
                "recommended": True,
                "target_tile": called_tile,
                "target_tile_display": display_tile(called_tile) if called_tile else None,
                "reason": "建议和牌。",
            }
        if op_type in (4, 5, 6):
            if current_shanten == 0:
                return {
                    "action": operation_type_label(op_type),
                    "recommended": False,
                    "target_tile": called_tile,
                    "target_tile_display": display_tile(called_tile) if called_tile else None,
                    "reason": "可杠，默认保守不建议开杠；除非你明确要加打点或已判断安全。",
                }
            return {
                "action": operation_type_label(op_type),
                "recommended": False,
                "target_tile": called_tile,
                "target_tile_display": display_tile(called_tile) if called_tile else None,
                "reason": "可杠，默认不建议。开杠会增加放铳和被反制风险。",
            }
        if best is None:
            return None

        label = operation_type_label(op_type)
        if self.riichi_seats and self.effective_safe_tiles() and current_shanten > 0:
            return {
                "action": label,
                "recommended": False,
                "target_tile": called_tile,
                "target_tile_display": display_tile(called_tile) if called_tile else None,
                "combination": best.get("combo"),
                "followup_discard": best["tile"],
                "followup_discard_display": display_tile(best["tile"]),
                "call_score": best.get("call_score"),
                "call_breakdown": best.get("call_breakdown"),
                "open_yaku_potential": best.get("yaku_profile", {}).get("score"),
                "yaku_tags": best.get("yaku_profile", {}).get("tags", []),
                "reason": f"不建议 {label} {display_tile(called_tile)}，场上已有明确威胁，当前更应优先保留退路。",
            }
        if best["shanten"] < current_shanten:
            return {
                "action": label,
                "recommended": True,
                "target_tile": called_tile,
                "target_tile_display": display_tile(called_tile) if called_tile else None,
                "combination": best.get("combo"),
                "followup_discard": best["tile"],
                "followup_discard_display": display_tile(best["tile"]),
                "call_score": best.get("call_score"),
                "call_breakdown": best.get("call_breakdown"),
                "open_yaku_potential": best.get("yaku_profile", {}).get("score"),
                "yaku_tags": best.get("yaku_profile", {}).get("tags", []),
                "reason": (
                    f"建议 {label} {display_tile(called_tile)}，可把向听从 {current_shanten} 压到 {best['shanten']}，"
                    f"鸣后优先切 {display_tile(best['tile'])}。"
                ),
            }
        if op_type == 3 and called_tile and self.is_value_honor(called_tile) and best["shanten"] <= current_shanten:
            return {
                "action": label,
                "recommended": True,
                "target_tile": called_tile,
                "target_tile_display": display_tile(called_tile),
                "combination": best.get("combo"),
                "followup_discard": best["tile"],
                "followup_discard_display": display_tile(best["tile"]),
                "call_score": best.get("call_score"),
                "call_breakdown": best.get("call_breakdown"),
                "open_yaku_potential": best.get("yaku_profile", {}).get("score"),
                "yaku_tags": best.get("yaku_profile", {}).get("tags", []),
                "reason": f"可碰 {display_tile(called_tile)}，是役牌/风牌碰牌，速度和打点都不差；保守建议可以碰。",
            }
        allow_same_shanten, same_shanten_reason = self.should_allow_same_shanten_call(best, op_type)
        if best["shanten"] == current_shanten and same_shanten_reason == "danger_block":
            return {
                "action": label,
                "recommended": False,
                "target_tile": called_tile,
                "target_tile_display": display_tile(called_tile) if called_tile else None,
                "combination": best.get("combo"),
                "followup_discard": best["tile"],
                "followup_discard_display": display_tile(best["tile"]),
                "call_score": best.get("call_score"),
                "call_breakdown": best.get("call_breakdown"),
                "open_yaku_potential": best.get("yaku_profile", {}).get("score"),
                "yaku_tags": best.get("yaku_profile", {}).get("tags", []),
                "reason": f"不建议 {label} {display_tile(called_tile)}，同向听鸣牌需要承担明显放铳风险，这里不值得强行提速。",
            }
        if best["shanten"] == current_shanten and allow_same_shanten:
            if same_shanten_reason == "aggressive_push":
                reason = f"可 {label} {display_tile(called_tile)}，虽然向听不变，但鸣后役种路线更清晰，适合积极提速。"
            elif same_shanten_reason == "riichi_exception":
                reason = f"可 {label} {display_tile(called_tile)}，场上虽有威胁，但鸣后听牌质量和收益都足够高，可以例外进攻。"
            elif same_shanten_reason == "chi_pattern_release":
                reason = f"可 {label} {display_tile(called_tile)}，这手很像典型断幺/一色寄副露路线，鸣后质量足够高，适合主动提速。"
            elif same_shanten_reason == "peng_tenpai_release":
                reason = f"可 {label} {display_tile(called_tile)}，这手不只是役牌副露，鸣后听牌质量也很高，可以主动顺着路线提速。"
            elif same_shanten_reason == "peng_pattern_release":
                reason = f"可 {label} {display_tile(called_tile)}，这手很像典型役牌复合副露路线，鸣后质量足够高，适合主动提速。"
            elif same_shanten_reason == "pattern_release":
                reason = f"可 {label} {display_tile(called_tile)}，这手鸣后很像典型高价值副露形，值得顺着役种路线主动提速。"
            else:
                reason = f"可 {label} {display_tile(called_tile)}，向听虽不变，但鸣后综合路线已经明显优于门清，可主动提速。"
            return {
                "action": label,
                "recommended": True,
                "target_tile": called_tile,
                "target_tile_display": display_tile(called_tile) if called_tile else None,
                "combination": best.get("combo"),
                "followup_discard": best["tile"],
                "followup_discard_display": display_tile(best["tile"]),
                "call_score": best.get("call_score"),
                "call_breakdown": best.get("call_breakdown"),
                "open_yaku_potential": best.get("yaku_profile", {}).get("score"),
                "yaku_tags": best.get("yaku_profile", {}).get("tags", []),
                "reason": reason,
            }
        if (
            best["shanten"] == current_shanten
            and (
                best["call_score"] >= 6.5
                or best["ukeire"] > current_ukeire + 4
                or best["efficiency_score"] >= current_ukeire * 4 + 18
            )
        ):
            return {
                "action": label,
                "recommended": True,
                "target_tile": called_tile,
                "target_tile_display": display_tile(called_tile) if called_tile else None,
                "combination": best.get("combo"),
                "followup_discard": best["tile"],
                "followup_discard_display": display_tile(best["tile"]),
                "call_score": best.get("call_score"),
                "call_breakdown": best.get("call_breakdown"),
                "open_yaku_potential": best.get("yaku_profile", {}).get("score"),
                "yaku_tags": best.get("yaku_profile", {}).get("tags", []),
                "reason": f"可 {label} {display_tile(called_tile)}，向听不变但鸣后速度/役种收益更好，优先切 {display_tile(best['tile'])}。",
            }
        return {
            "action": label,
            "recommended": False,
            "target_tile": called_tile,
            "target_tile_display": display_tile(called_tile) if called_tile else None,
            "combination": best.get("combo"),
            "followup_discard": best["tile"],
            "followup_discard_display": display_tile(best["tile"]),
            "call_score": best.get("call_score"),
            "call_breakdown": best.get("call_breakdown"),
            "open_yaku_potential": best.get("yaku_profile", {}).get("score"),
            "yaku_tags": best.get("yaku_profile", {}).get("tags", []),
            "reason": self.same_shanten_reject_reason(called_tile, label, best),
        }

    def _remove_one_from_list(self, tiles, tile):
        if tile in tiles:
            tiles.remove(tile)
            return
        normalized = normalize_tile(tile)
        match = next((t for t in tiles if normalize_tile(t) == normalized), None)
        if match:
            tiles.remove(match)

    def build_tenpai_advice(self, data):
        tingpais = data.get("tingpais") or []
        if not tingpais:
            return None
        menzen = self.open_melds == 0
        parts = []
        for item in tingpais:
            discard_tile = item.get("tile")
            infos = item.get("infos") or []
            waits = [info.get("tile") for info in infos if info.get("tile")]
            count = sum(info.get("count", 0) for info in infos if info.get("haveyi"))
            if waits:
                parts.append(f"打{display_tile(discard_tile)}听 {format_waits(waits)} ({count}枚)")
        if not parts:
            return None
        prefix = "门清听牌。" if menzen else "已听牌。"
        return prefix + " " + "；".join(parts[:3])

    def evaluate_tenpai_options(self, data):
        options = []
        for item in data.get("tingpais") or []:
            discard_tile = item.get("tile")
            zhenting = bool(item.get("zhenting"))
            infos = item.get("infos") or []
            waits = []
            live = 0
            max_han = 0
            has_yaku = False
            riichi_nominal = 0.0
            for info in infos:
                wait_tile = info.get("tile")
                if not wait_tile:
                    continue
                waits.append(wait_tile)
                remaining = max(0, 4 - self.visible_counts[tile_to_index(wait_tile)])
                live += remaining
                has_yaku = has_yaku or bool(info.get("haveyi"))
                max_han = max(max_han, safe_int(info.get("count", 0)))
                riichi_nominal = max(riichi_nominal, float(safe_int(info.get("point_rong"), 0)))
            if waits:
                shape = wait_shape_score(waits)
                score = round(
                    live * 1.5
                    + shape * 3.5
                    + max_han * 1.2
                    + min(riichi_nominal / 2000.0, 3.0)
                    + (0.6 if has_yaku else -0.8),
                    2,
                )
                options.append({
                    "discard": discard_tile,
                    "zhenting": zhenting,
                    "waits": waits,
                    "live": live,
                    "max_han": max_han,
                    "has_yaku": has_yaku,
                    "shape_score": shape,
                    "riichi_nominal": riichi_nominal,
                    "score": score,
                })
        options.sort(key=lambda item: (item["zhenting"], -item["score"], -item["live"], -item["max_han"]))
        return options

    def riichi_push_value(self, option):
        score_ctx = self.score_context() or {}
        tilt = self.strategic_tilt()
        value = 0.0
        value += option["live"] * 0.55
        value += option["shape_score"] * 1.8
        value += min(option["max_han"], 5) * 0.7
        value += min(option.get("riichi_nominal", 0.0) / 4000.0, 1.5)
        if self.is_dealer():
            value += 0.8
        if tilt == "积极":
            value += 0.8
        elif tilt == "保守":
            value -= 0.6
        if self.is_all_last():
            if score_ctx.get("place") == 4:
                value += 1.1
            elif score_ctx.get("place") == 1 and score_ctx.get("last_gap", 0) > 4000:
                value -= 1.2
        if self.defensive_pressure() >= 4:
            value -= 0.9
        elif self.riichi_seats:
            value -= 0.5
        return round(value, 2)

    def riichi_decision_template(self, option, push_value):
        score_ctx = self.score_context() or {}
        tilt = self.strategic_tilt()
        if option["zhenting"]:
            return "furiten_damaten"
        if self.open_melds:
            return "open_hand_damaten"
        if (
            self.is_all_last()
            and score_ctx.get("place") == 1
            and score_ctx.get("last_gap", 0) > 4000
            and option["max_han"] >= 2
        ):
            return "all_last_protect_damaten"
        if self.defensive_pressure() >= 4 and option["live"] <= 3 and option["max_han"] >= 2:
            return "threat_damaten"
        if option["live"] <= 2 and option["shape_score"] <= 0.8 and option.get("riichi_nominal", 0) >= 7700:
            return "value_damaten"
        if option["max_han"] >= 4 or option.get("riichi_nominal", 0) >= 11600:
            return "high_value_damaten"
        if self.is_dealer() and option["live"] >= 4 and option["shape_score"] >= 1.2 and option["max_han"] <= 3:
            return "dealer_riichi"
        if tilt == "积极" and option["live"] >= 3 and option["shape_score"] >= 1.0:
            return "aggressive_riichi"
        if option["live"] >= 5 and option["shape_score"] >= 1.2 and option["max_han"] <= 2:
            return "good_shape_riichi"
        if self.riichi_seats and push_value <= 2.4:
            return "threat_riichi_check"
        if push_value >= 5.2:
            return "push_value_riichi"
        return "default_riichi"

    def riichi_template_note(self, template):
        notes = {
            "furiten_damaten": "振听局面，默认不立直。",
            "open_hand_damaten": "已副露听牌，按默听处理。",
            "all_last_protect_damaten": "终局领先时优先守顺位，不为一般增益立直。",
            "threat_damaten": "场压偏高且待牌一般，有打点时更偏向默听。",
            "value_damaten": "愚形但已有足够打点，优先保留默听收支。",
            "high_value_damaten": "打点已高，不急着靠立直再抬收益。",
            "dealer_riichi": "亲家好形听牌，立直收益和连庄价值都高。",
            "aggressive_riichi": "当前点况要求更积极争和，立直更符合收支。",
            "good_shape_riichi": "好形低打点听牌，立直补收益最自然。",
            "threat_riichi_check": "场上已有威胁，当前立直收益不足以覆盖风险。",
            "push_value_riichi": "听牌质量和局况都支持主动进攻。",
            "default_riichi": "默认按门清立直收益处理。",
        }
        return notes.get(template)

    def build_riichi_advice(self, data):
        options = self.evaluate_tenpai_options(data)
        if not options:
            self.last_tenpai_analysis = None
            return None

        best = options[0]
        self.last_tenpai_analysis = {
            "best_discard": best["discard"],
            "best_discard_display": display_tile(best["discard"]),
            "options": [
                {
                    "discard": item["discard"],
                    "discard_display": display_tile(item["discard"]),
                    "waits": item["waits"],
                    "waits_display": [display_tile(tile) for tile in item["waits"]],
                    "live": item["live"],
                    "shape_score": item["shape_score"],
                    "max_han": item["max_han"],
                    "riichi_nominal": item.get("riichi_nominal", 0.0),
                    "score": item["score"],
                    "zhenting": item["zhenting"],
                }
                for item in options[:3]
            ],
        }
        score_ctx = self.score_context() or {}
        tilt = self.strategic_tilt()
        push_value = self.riichi_push_value(best)
        decision_template = self.riichi_decision_template(best, push_value)
        self.last_tenpai_analysis["decision_template"] = decision_template
        self.last_tenpai_analysis["push_value"] = push_value
        self.last_tenpai_analysis["tilt"] = tilt
        self.last_tenpai_analysis["template_note"] = self.riichi_template_note(decision_template)
        best_desc = (
            f"最佳听牌: 打{display_tile(best['discard'])}听 {format_waits(best['waits'])} "
            f"(场上可见后剩 {best['live']} 枚, 形状 {best['shape_score']}, "
            f"最高番数 {best['max_han']}, 名义打点 {int(best.get('riichi_nominal', 0))})"
        )

        if decision_template == "furiten_damaten":
            return f"{best_desc}。当前振听，不建议立直。"

        if not self.open_melds:
            if decision_template == "all_last_protect_damaten":
                return f"{best_desc}。终局领先，优先默听守顺位，不建议为一般增益立直。"
            if decision_template == "threat_damaten":
                return f"{best_desc}。场上威胁较高，待牌一般且已有打点，偏向默听。"
            if decision_template == "dealer_riichi":
                return f"{best_desc}。亲家听牌，建议立直争取连庄与打点。"
            if decision_template == "aggressive_riichi":
                return f"{best_desc}。当前点况更需要和牌/打点，建议立直。"
            if decision_template == "good_shape_riichi":
                return f"{best_desc}。建议立直：待牌不差，门清收益更高。"
            if decision_template in ("value_damaten", "high_value_damaten"):
                return f"{best_desc}。更建议默听：待牌少，但已有足够打点。"
            if best["live"] <= 2 and best["shape_score"] <= 0.85:
                return f"{best_desc}。待牌偏少，保守建议先默听。"
            if decision_template == "threat_riichi_check":
                return f"{best_desc}。场上已有立直/威胁，听牌质量一般，偏向默听。"
            if decision_template == "push_value_riichi":
                return f"{best_desc}。听牌质量和局况都支持进攻，建议立直。"
            return f"{best_desc}。默认建议立直。"

        if decision_template == "open_hand_damaten" and best["has_yaku"]:
            return f"{best_desc}。已副露听牌，不能立直，按默听处理。"
        return f"{best_desc}。当前听牌但未确认稳定役种，谨慎处理。"

    def build_operation_notice(self, data):
        operation = data.get("operation") or {}
        if operation.get("seat") != self.self_seat:
            return None
        ops = operation.get("operation_list") or []
        if not ops:
            return None

        lines = []
        chosen_plan = None
        for item in ops:
            op_type = item.get("type")
            if op_type == 1:
                continue
            label = operation_type_label(op_type)
            combinations = item.get("combination") or []
            called_tile = data.get("tile")
            combo_text = ""
            if combinations:
                pretty = [
                    "|".join(display_tile(tile) for tile in combo.split("|"))
                    for combo in combinations
                ]
                combo_text = f" {pretty}"
            lines.append(f"可操作: {label}{combo_text}")
            plan = self.build_call_plan(op_type, combinations, called_tile)
            if plan:
                lines.append(plan["reason"])
                if chosen_plan is None or (plan.get("recommended") and not chosen_plan.get("recommended")):
                    chosen_plan = plan
        if chosen_plan:
            chosen_plan = {
                **chosen_plan,
                "kind": "operation",
                "round": self.round_label,
                "seat": self.self_seat,
                "trigger_tile": data.get("tile"),
                "trigger_tile_display": display_tile(data.get("tile")) if data.get("tile") else None,
                "riichi_pressure": self.defensive_pressure(),
                "safe_tiles_before_call": self.effective_safe_tiles(),
            }
        self.last_action_plan = chosen_plan
        return "\n".join(lines) if lines else None

    def seat_name(self, seat):
        return self.seat_names.get(seat, f"seat {seat}")

    def round_name(self, data):
        return pmh.format_round_name(data.get("chang"), data.get("ju"))

    def apply_request(self, request_id, method_name, decoded):
        self.pending_requests[request_id] = method_name
        if method_name.endswith(".authGame"):
            self.self_account_id = decoded.get("account_id")
        if method_name.endswith(".inputChiPengGang"):
            self.pending_self_call = decoded

    def apply_response(self, request_id, schema, body):
        request_method = self.pending_requests.get(request_id, "")
        decoded = pmh.decode_message_body(schema, request_method, body, 3)
        if request_method.endswith(".authGame"):
            players = decoded.get("players", [])
            for player in players:
                self.player_lookup[player.get("account_id")] = player.get("nickname")
            self.seat_list = decoded.get("seat_list", [])
            if self.self_account_id in self.seat_list:
                self.self_seat = self.seat_list.index(self.self_account_id)
            self.seat_names = {
                seat: self.player_lookup.get(account_id, f"account:{account_id}")
                for seat, account_id in enumerate(self.seat_list)
            }

    def decode_action(self, schema, body):
        action = pmh.decode_action_prototype(schema, body)
        action_data = action.get("data")
        if action.get("name") == "ActionDealTile" and isinstance(action_data, dict):
            if action_data.get("seat") is None and action_data.get("tile") and self.self_seat is not None:
                action_data["seat"] = self.self_seat
            if action_data.get("seat") is None and isinstance(self.last_discard_data, dict):
                prev_seat = self.last_discard_data.get("seat")
                if prev_seat is not None and self.seat_list:
                    action_data["seat"] = (prev_seat + 1) % len(self.seat_list)
        if action.get("name") == "ActionDiscardTile" and isinstance(action_data, dict):
            if action_data.get("seat") is None and self.last_deal_seat is not None:
                action_data["seat"] = self.last_deal_seat
            if (
                action_data.get("seat") is None
                and self.last_action_name == "ActionChiPengGang"
                and isinstance(self.last_action_data, dict)
            ):
                action_data["seat"] = self.last_action_data.get("seat")
        if (
            action.get("name") == "ActionChiPengGang"
            and self.pending_self_call
            and isinstance(action_data, dict)
            and action_data.get("seat") is None
            and self.self_seat is not None
        ):
            inferred_type = self.pending_self_call.get("type")
            if inferred_type == 2:
                inferred_type = 0
            elif inferred_type == 3:
                inferred_type = 1
            action_data["seat"] = self.self_seat
            if inferred_type is not None:
                action_data["type"] = inferred_type
        if (
            action.get("name") == "ActionChiPengGang"
            and isinstance(action_data, dict)
            and not action_data.get("tiles")
            and isinstance(self.last_discard_data, dict)
            and self.last_discard_data.get("tile")
        ):
            action_data["tiles"] = [self.last_discard_data["tile"]]
        return action

    def remove_tiles(self, tiles):
        for tile in tiles:
            if tile in self.hand:
                self.hand.remove(tile)
                continue
            normalized = normalize_tile(tile)
            match = next((t for t in self.hand if normalize_tile(t) == normalized), None)
            if match:
                self.hand.remove(match)

    def apply_self_call(self, data):
        tiles = list(data.get("tiles") or [])
        froms = list(data.get("froms") or [])
        seat = data.get("seat")
        call_type = data.get("type")
        if seat != self.self_seat or not tiles:
            return

        if froms and len(froms) == len(tiles):
            consumed = [tile for tile, source in zip(tiles, froms) if source == self.self_seat]
            self.remove_tiles(consumed)
            self.open_melds += 1
            return

        if call_type == 1:
            self.remove_tiles(tiles[:2])
            self.open_melds += 1
        elif call_type == 0:
            self.remove_tiles(tiles[:2])
            self.open_melds += 1
        elif call_type == 2:
            self.remove_tiles(tiles[:3])
            self.open_melds += 1

    def apply_self_angang(self, data):
        seat = data.get("seat")
        if seat != self.self_seat:
            return
        call_type = data.get("type")
        tiles = data.get("tiles")
        if isinstance(tiles, str):
            self.record_meld(seat, self.normalized_meld_type(call_type), [tiles] * (1 if call_type == 3 else 4))
            if call_type == 3:
                self.remove_tiles([tiles])
            else:
                self.remove_tiles([tiles] * 4)
                self.open_melds += 1

    def apply_public_call_visibility(self, data):
        tiles = list(data.get("tiles") or [])
        if not tiles:
            return
        froms = list(data.get("froms") or [])
        seat = data.get("seat")
        if seat is not None:
            self.open_melds_by_seat[seat] = self.open_melds_by_seat.get(seat, 0) + 1
            self.record_meld(seat, self.normalized_meld_type(data.get("type")), tiles, froms)
        if froms and len(froms) == len(tiles):
            consumed = [tile for tile, source in zip(tiles, froms) if source == seat]
            self.add_visible_tiles(consumed)
            return
        call_type = data.get("type")
        if call_type in (0, 1):
            self.add_visible_tiles(tiles[:2])
        elif call_type == 2:
            self.add_visible_tiles(tiles[:3])

    def suggestion_text(self):
        options = self.evaluate_discard_options()
        best = options[0]
        alts = options[1:3]
        best_danger = self.tile_danger_score(best["tile"])
        max_danger = self.max_seat_danger(best["tile"]) if self.riichi_seats else 0.0
        confidence = self.recommendation_confidence(options)
        parts = [
            f"推荐切 {display_tile(best['tile'])}",
            f"向听={best['shanten']}",
            f"进张={best['ukeire']}",
            f"两步={best.get('advance_ukeire', 0)}/{best.get('improvement_ukeire', 0)}",
            f"信心={confidence_label(confidence)}({confidence})",
        ]
        turn = self.estimated_turn()
        if turn is not None:
            parts.append(f"巡目~{turn}")
        phase = self.phase_label()
        if phase:
            parts.append(phase)
        score_ctx = self.score_context()
        if score_ctx:
            parts.append(f"顺位={score_ctx['place']}")
        parts.append("亲家" if self.is_dealer() else "子家")
        tilt = self.strategic_tilt()
        if tilt:
            parts.append(f"倾向={tilt}")
        if self.riichi_seats:
            parts.append(f"危险度={self.danger_label(best_danger)}({best_danger})")
            parts.append(f"单家峰值={round(max_danger, 1)}")
            parts.append(f"场压={self.pressure_label()}")
        if best["improving"]:
            parts.append(f"改良={','.join(display_tile(tile) for tile in best['improving'][:8])}")
        if best.get("future_ukeire"):
            parts.append(f"后续均值={best['future_ukeire']}")
        if best.get("risk_reward_tags"):
            parts.append(f"标签={','.join(best['risk_reward_tags'])}")
        lines = [" | ".join(parts)]
        if alts:
            alt_text = "；".join(
                (
                    f"{display_tile(item['tile'])} (向听{item['shanten']}, 进张{item['ukeire']}"
                    + f", 两步{item.get('advance_ukeire', 0)}/{item.get('improvement_ukeire', 0)}"
                    + (
                        f", 标签{'/'.join(item.get('risk_reward_tags', []))}"
                        if item.get("risk_reward_tags") else ""
                    )
                    + (
                        f", 危险{self.tile_danger_score(item['tile'])}"
                        if self.riichi_seats else ""
                    )
                    + ")"
                )
                for item in alts
            )
            lines.append(f"备选: {alt_text}")
        if self.should_fold_strictly(best):
            safe_tiles = self.effective_safe_tiles()
            safe_text = ",".join(display_tile(tile) for tile in safe_tiles[:4])
            lines.append(f"撤退提示: 当前更偏向收手；手里已有相对安全牌 {safe_text}，优先考虑不押。")
        if self.riichi_seats and max_danger >= 2.0 and best["shanten"] > 0:
            lines.append("防守提示: 场上已有立直，当前推荐牌仍偏危险；如果有现物/字牌安牌，优先考虑撤退。")
        if self.defensive_pressure() >= 4 and best["shanten"] > 0:
            lines.append("押退提示: 多家威胁或后巡，当前更应重视安全度，不建议为一般进张强押。")
        push_template = self.discard_push_template(best)
        if push_template == "high_risk_tenpai_push":
            lines.append("押退提示: 这是高风险高回报的听牌推进，只有在你接受明显放铳风险时才值得继续押。")
        elif push_template == "high_risk_1shanten_push":
            lines.append("押退提示: 这是高风险的一向听推进，通常只在点况需要时才值得继续押。")
        elif push_template == "high_value_risky_push":
            lines.append("押退提示: 这手兼具打点路线和危险度，属于高风险高价值选择，不是常规安全推荐。")
        policy_text = self.discard_policy_note_text()
        if policy_text:
            lines.append(policy_text)
        if score_ctx and score_ctx["place"] == 4 and score_ctx["top_gap"] > 12000 and best["shanten"] <= 1:
            lines.append("点况提示: 当前落后较多，必要时可以比平时更积极一些。")
        if self.is_all_last() and score_ctx:
            if score_ctx["place"] == 1 and score_ctx["last_gap"] > 4000:
                lines.append("收支提示: 终局领先，当前优先守住顺位，不值得为一般牌效冒险。")
            elif score_ctx["place"] == 4:
                lines.append("收支提示: 终局落后，允许比平时更积极，优先保留逆转路线。")
        if tilt == "积极" and best["shanten"] <= 1 and best_danger <= 1.6:
            lines.append("局况提示: 当前更需要争取和牌，若不是明显危险牌，可以适度继续进攻。")
        if tilt == "保守" and self.riichi_seats and max_danger >= 1.2:
            lines.append("局况提示: 当前分数和局况更适合守成，这类牌不值得为普通进张去押。")
        if confidence < 0.55:
            lines.append("不确定性提示: 这手规则判断优势不大，适合导出摘要后再问模型。")
        return "\n".join(lines)

    def effective_hand_tiles(self):
        return len(self.hand) + self.open_melds * 3

    def can_offer_discard_suggestion(self):
        return self.hand_seeded and self.effective_hand_tiles() >= 14

    def apply_action(self, action, event_index, emit_suggestion=True):
        self.event_index = event_index
        name = action.get("name")
        data = action.get("data")
        output = None
        self.last_action_plan = None
        self.last_tenpai_analysis = None

        if name == "ActionNewRound" and isinstance(data, dict):
            self.chang = data.get("chang")
            self.ju = data.get("ju")
            self.ben = data.get("ben", 0)
            self.liqibang = data.get("liqibang", 0)
            self.round_label = self.round_name(data)
            self.dora_indicators = list(data.get("doras") or [])
            self.hand = list(data.get("tiles") or [])
            self.hand_seeded = bool(self.hand)
            self.visible_counts = [0] * 34
            self.discards_by_seat = {seat: [] for seat in range(4)}
            self.discard_meta_by_seat = {seat: [] for seat in range(4)}
            self.riichi_seats = set()
            self.riichi_event_index = {}
            self.open_melds_by_seat = {seat: 0 for seat in range(4)}
            self.melds_by_seat = {seat: [] for seat in range(4)}
            self.current_scores = list(data.get("scores") or [])
            self.left_tile_count = data.get("left_tile_count")
            self.add_visible_tiles(self.dora_indicators)
            self.open_melds = 0
            self.last_suggestion_key = None
            if emit_suggestion and len(self.hand) == 14:
                output = self.build_suggestion("起手配牌")

        elif name == "ActionDealTile" and isinstance(data, dict):
            seat = data.get("seat")
            tile = data.get("tile")
            if data.get("left_tile_count") is not None:
                self.left_tile_count = data.get("left_tile_count")
            if self.self_seat is None and seat is not None and tile:
                self.self_seat = seat
                if seat not in self.seat_names:
                    self.seat_names[seat] = "you"
            if seat == self.self_seat:
                if tile:
                    if not self.hand_seeded:
                        self.hand = []
                    self.hand.append(tile)
                if self.hand_seeded and emit_suggestion:
                    output = self.build_suggestion(f"自摸 {display_tile(tile) if tile else '?'}")
                    tenpai_advice = self.build_tenpai_advice(data)
                    if tenpai_advice:
                        output = f"{output}\n{tenpai_advice}"
                    riichi_advice = self.build_riichi_advice(data)
                    if riichi_advice:
                        output = f"{output}\n{riichi_advice}"
                    if output is None:
                        output = f"[live] 已识别到你的自摸 {display_tile(tile) if tile else '?'}，但本次建议被去重/状态条件跳过。"
                elif emit_suggestion and tile:
                    output = "[live] 已识别你的座位，但这局是中途接入，尚未拿到完整起手；请等下一局开始后再给建议。"
            self.last_deal_seat = seat

        elif name == "ActionDiscardTile" and isinstance(data, dict):
            seat = data.get("seat")
            tile = data.get("tile")
            if data.get("scores"):
                self.current_scores = list(data.get("scores") or self.current_scores)
            if data.get("liqibang") is not None:
                self.liqibang = data.get("liqibang")
            if seat == self.self_seat:
                if tile:
                    if self.hand_seeded:
                        self.remove_tiles([tile])
            if seat is not None and tile:
                self.discards_by_seat.setdefault(seat, []).append(tile)
                self.discard_meta_by_seat.setdefault(seat, []).append({
                    "tile": tile,
                    "moqie": bool(data.get("moqie")),
                    "is_liqi": bool(data.get("is_liqi")),
                    "event_index": self.event_index,
                })
            if tile:
                self.add_visible_tile(tile)
            if data.get("is_liqi") and seat is not None:
                self.riichi_seats.add(seat)
                self.riichi_event_index[seat] = self.event_index
            self.last_deal_seat = None
            self.last_discard_data = data
            if emit_suggestion:
                op_notice = self.build_operation_notice(data)
                if op_notice:
                    output = op_notice

        elif name == "ActionChiPengGang" and isinstance(data, dict):
            self.apply_public_call_visibility(data)
            self.apply_self_call(data)
            self.pending_self_call = None
            if emit_suggestion and data.get("seat") == self.self_seat and self.can_offer_discard_suggestion():
                output = self.build_suggestion(action_call_type_label(data.get("type")))
            if emit_suggestion:
                tenpai_advice = self.build_tenpai_advice(data)
                if tenpai_advice:
                    output = f"{output}\n{tenpai_advice}" if output else tenpai_advice
                riichi_advice = self.build_riichi_advice(data)
                if riichi_advice:
                    output = f"{output}\n{riichi_advice}" if output else riichi_advice

        elif name == "ActionAnGangAddGang" and isinstance(data, dict):
            tiles = data.get("tiles")
            call_type = data.get("type")
            if isinstance(tiles, str):
                if call_type == 3:
                    self.add_visible_tile(tiles)
                else:
                    self.add_visible_tiles([tiles] * 4)
            self.apply_self_angang(data)

        self.last_action_name = name
        self.last_action_data = data if isinstance(data, dict) else None
        return output

    def build_suggestion(self, trigger):
        if not self.can_offer_discard_suggestion():
            return None
        key = (
            self.event_index,
            self.round_label,
            tuple(sorted(self.hand, key=tile_sort_key)),
            tuple(self.dora_indicators),
            trigger,
        )
        if key == self.last_suggestion_key:
            return None
        self.last_suggestion_key = key
        hand_text = format_tiles(self.hand)
        title = f"[{self.round_label}] {trigger} | 手牌: {hand_text}"
        options = self.evaluate_discard_options()
        self.last_decision_snapshot = self.build_decision_snapshot(trigger, options)
        best = options[0]
        self.last_action_plan = {
            "kind": "discard",
            "round": self.round_label,
            "seat": self.self_seat,
            "trigger": trigger,
            "tile": best["tile"],
            "tile_display": display_tile(best["tile"]),
            "hand_order": list(self.hand),
            "hand_order_display": [display_tile(tile) for tile in self.hand],
            "draw_tile": self.hand[-1] if self.hand else None,
            "draw_tile_display": display_tile(self.hand[-1]) if self.hand else None,
            "shanten": best["shanten"],
            "ukeire": best["ukeire"],
            "confidence": self.last_decision_snapshot.get("confidence"),
        }
        body = self.suggestion_text()
        return f"{title}\n{body}"


def parse_har_actions(path):
    har = json.loads(Path(path).read_text(encoding="utf-8"))
    schema = pmh.LiqiSchema(pmh.extract_liqi_schema(har))
    messages = pmh.extract_game_gateway_messages(har)
    state = LiveGameState()
    outputs = []

    for index, message in enumerate(messages):
        raw = base64.b64decode(message["data"])
        frame_type, request_id, method_name, body = pmh.parse_frame(raw)
        if frame_type == 2:
            decoded = pmh.decode_message_body(schema, method_name, body, frame_type)
            state.apply_request(request_id, method_name, decoded)
        elif frame_type == 3:
            state.apply_response(request_id, schema, body)
        elif frame_type == 1 and method_name == ".lq.ActionPrototype":
            action = state.decode_action(schema, body)
            suggestion = state.apply_action(action, index)
            if suggestion:
                outputs.append({
                    "index": index,
                    "suggestion": suggestion,
                    "snapshot": state.last_decision_snapshot,
                    "action_plan": state.last_action_plan,
                    "tenpai_analysis": state.last_tenpai_analysis,
                })

    return len(messages), outputs


def load_manifest_index(manifest_path):
    path = Path(manifest_path)
    if not path.exists():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(rows, dict):
        rows = rows.get("pairs") or rows.get("rows") or rows.get("items") or []
    index = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        uuid = row.get("uuid")
        if uuid:
            index[uuid] = row
    return index


def discover_manifest_candidates(paipu_path):
    path = Path(paipu_path)
    candidates = []
    local = path.parent / "manifest.json"
    if local.exists():
        candidates.append(local)
    parent = path.parent.parent
    if parent.exists():
        for sibling in parent.iterdir():
            if not sibling.is_dir() or sibling == path.parent:
                continue
            manifest = sibling / "manifest.json"
            if manifest.exists():
                candidates.append(manifest)
    return candidates


def resolve_manifest_row(paipu_path, uuid, manifest_path=None):
    checked = []
    if manifest_path:
        checked.append(Path(manifest_path))
    checked.extend(discover_manifest_candidates(paipu_path))
    seen = set()
    best = {}
    for manifest in checked:
        manifest = Path(manifest)
        if manifest in seen:
            continue
        seen.add(manifest)
        row = load_manifest_index(manifest).get(uuid)
        if not row:
            continue
        if row.get("players"):
            return row
        if not best:
            best = row
    return best


def decode_record_wrapper(schema, payload):
    raw = base64.b64decode(payload)
    name = None
    body = None
    for field_id, wire_type, value in pmh.parse_simple_protobuf(raw):
        if field_id == 1 and wire_type == 2:
            name = value.decode("utf-8", errors="replace")
        elif field_id == 2 and wire_type == 2:
            body = value
    if not name or not body:
        return None
    short_name = name.split(".")[-1]
    decoded = schema.decode_message(body, short_name)
    return {
        "name": name,
        "short_name": short_name,
        "data": decoded,
    }


def record_to_action(record_name, data, self_seat):
    if not isinstance(data, dict):
        return None
    if record_name == "RecordNewRound":
        tiles = list(data.get(f"tiles{self_seat}") or [])
        normalized = dict(data)
        normalized["tiles"] = tiles
        return {"name": "ActionNewRound", "data": normalized}
    if record_name == "RecordDealTile":
        return {"name": "ActionDealTile", "data": dict(data)}
    if record_name == "RecordDiscardTile":
        return {"name": "ActionDiscardTile", "data": dict(data)}
    if record_name == "RecordChiPengGang":
        return {"name": "ActionChiPengGang", "data": dict(data)}
    if record_name == "RecordAnGangAddGang":
        return {"name": "ActionAnGangAddGang", "data": dict(data)}
    if record_name == "RecordHule":
        return {"name": "ActionHule", "data": dict(data)}
    if record_name == "RecordNoTile":
        return {"name": "ActionNoTile", "data": dict(data)}
    return None


def record_accounts_mapping(record):
    accounts = ((record.get("head") or {}).get("accounts") or [])
    seat_names = {}
    for item in accounts:
        seat = item.get("seat")
        nickname = item.get("nickname")
        if seat is None or nickname is None:
            continue
        seat_names[safe_int(seat, seat)] = nickname
    return seat_names


def parse_paipu_actions(path, player_name=None, manifest_path=None, target_indices=None, max_index=None):
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    uuid = ((record.get("head") or {}).get("uuid")) or Path(path).stem
    manifest_row = resolve_manifest_row(path, uuid, manifest_path)
    players = manifest_row.get("players") or []
    record_seat_names = record_accounts_mapping(record)
    state = LiveGameState()
    if record_seat_names:
        state.seat_names = dict(sorted(record_seat_names.items()))
    elif players:
        state.seat_names = {seat: name for seat, name in enumerate(players)}
    if player_name and record_seat_names:
        for seat, name in record_seat_names.items():
            if name == player_name:
                state.self_seat = seat
                break
    elif record_seat_names and "Levey" in record_seat_names.values():
        for seat, name in record_seat_names.items():
            if name == "Levey":
                state.self_seat = seat
                break
    elif player_name and players and player_name in players:
        state.self_seat = players.index(player_name)
    elif players and "Levey" in players:
        state.self_seat = players.index("Levey")
    else:
        state.self_seat = 0

    schema = pmh.LiqiSchema(json.loads(Path("/Users/bigo/code/mj/liqi.json").read_text(encoding="utf-8")))
    outputs = []
    actions = ((record.get("game_detail_records") or {}).get("actions") or [])
    decoded_count = 0
    target_indices = set(target_indices or [])
    for index, item in enumerate(actions):
        if max_index is not None and index > max_index:
            break
        payload = ((item.get("result") or {}).get("_base64"))
        if not payload:
            continue
        wrapped = decode_record_wrapper(schema, payload)
        if not wrapped:
            continue
        action = record_to_action(wrapped["short_name"], wrapped["data"], state.self_seat)
        if not action:
            continue
        decoded_count += 1
        suggestion = state.apply_action(action, index)
        if suggestion:
            if target_indices and index not in target_indices:
                continue
            outputs.append({
                "index": index,
                "suggestion": suggestion,
                "snapshot": state.last_decision_snapshot,
                "action_plan": state.last_action_plan,
                "tenpai_analysis": state.last_tenpai_analysis,
            })
    return decoded_count, outputs


def write_snapshot_jsonl(snapshot_path, outputs):
    target = Path(snapshot_path)
    lines = []
    for item in outputs:
        payload = {
            "index": item["index"],
            "suggestion": item["suggestion"],
            "snapshot": item.get("snapshot"),
            "action_plan": item.get("action_plan"),
            "tenpai_analysis": item.get("tenpai_analysis"),
        }
        lines.append(json.dumps(payload, ensure_ascii=False))
    target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def run_once(path, snapshot_jsonl=None):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict) and (raw.get("game_detail_records") or {}).get("actions"):
        total_messages, outputs = parse_paipu_actions(path)
    else:
        total_messages, outputs = parse_har_actions(path)
    print(f"HAR: {path}")
    print(f"Messages: {total_messages}")
    if snapshot_jsonl:
        write_snapshot_jsonl(snapshot_jsonl, outputs)
        print(f"Snapshots: {snapshot_jsonl}")
    print("")
    for item in outputs:
        print(f"[msg {item['index']:04d}]")
        print(item["suggestion"])
        print("")


def run_watch(path, interval, snapshot_jsonl=None):
    last_mtime = None
    last_count = -1
    last_output_index = -1
    last_message_count = -1
    print(f"Watching HAR: {path}")
    print("覆盖保存 HAR 后，这里会自动解析新状态并在你摸牌后给建议。")
    while True:
        target = Path(path)
        if not target.exists():
            time.sleep(interval)
            continue
        stat = target.stat()
        if last_mtime is None or stat.st_mtime != last_mtime or stat.st_size != last_count:
            try:
                message_count, outputs = parse_har_actions(path)
            except Exception as exc:
                print(f"[watch] parse failed: {exc}")
                time.sleep(interval)
                continue
            if snapshot_jsonl:
                write_snapshot_jsonl(snapshot_jsonl, outputs)
            if message_count < last_message_count:
                last_output_index = -1
            for item in outputs:
                if item["index"] <= last_output_index:
                    continue
                print("")
                print(f"[msg {item['index']:04d}]")
                print(item["suggestion"])
                last_output_index = item["index"]
            last_message_count = message_count
            last_mtime = stat.st_mtime
            last_count = stat.st_size
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="Majsoul live helper based on exported HAR data.")
    parser.add_argument("har", help="Path to HAR file")
    parser.add_argument("--watch", action="store_true", help="Poll the HAR file and print new suggestions")
    parser.add_argument("--interval", type=float, default=2.0, help="Watch polling interval in seconds")
    parser.add_argument("--snapshot-jsonl", help="Optional path to export structured decision snapshots")
    args = parser.parse_args()

    if args.watch:
        run_watch(args.har, args.interval, args.snapshot_jsonl)
    else:
        run_once(args.har, args.snapshot_jsonl)


if __name__ == "__main__":
    main()
