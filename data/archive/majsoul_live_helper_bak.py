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


def recommend_discards(tiles, indicators, open_melds=0, visible_counts=None):
    normalized_counts = hand_to_counts(tiles)
    unique_tiles = sorted(set(tiles), key=tile_sort_key)
    actual_dora = dora_set(indicators)
    options = []

    for tile in unique_tiles:
        counts = normalized_counts[:]
        counts[tile_to_index(tile)] -= 1
        shanten_value = total_shanten(counts, open_melds)
        ukeire_count, improving = ukeire_for_counts(counts, shanten_value, open_melds, visible_counts)
        keep_value = 0
        normalized = normalize_tile(tile)
        if normalized in actual_dora:
            keep_value += 2
        if tile[0] == "0":
            keep_value += 1
        if normalized[1] == "z":
            keep_value -= 0.2
        options.append({
            "tile": tile,
            "shanten": shanten_value,
            "ukeire": ukeire_count,
            "improving": improving,
            "danger_penalty": keep_value,
        })

    options.sort(
        key=lambda item: (
            item["shanten"],
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
        self.riichi_seats = set()
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
            if self.tile_danger_score(tile) <= 0.9
        ]

    def riichi_state(self):
        return {
            "self_riichi": self.self_seat in self.riichi_seats if self.self_seat is not None else False,
            "riichi_seats": sorted(self.riichi_seats),
            "riichi_seats_display": [self.seat_name(seat) for seat in sorted(self.riichi_seats)],
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

    def tile_danger_score(self, tile):
        normalized = normalize_tile(tile)
        if not self.riichi_seats:
            return 0.0
        danger = 0.0
        for seat in self.riichi_seats:
            river = self.discards_by_seat.get(seat, [])
            river_norm = {normalize_tile(t) for t in river}
            if normalized in river_norm:
                continue
            if normalized[1] == "z":
                visible = self.visible_counts[tile_to_index(normalized)]
                if visible >= 3:
                    danger += 0.3
                elif visible == 2:
                    danger += 0.8
                else:
                    danger += 1.6
                continue

            partners = tile_suji_partners(normalized)
            if partners and all(partner in river_norm for partner in partners):
                danger += 0.6
            elif partners and any(partner in river_norm for partner in partners):
                danger += 1.2
            else:
                danger += 2.2

            number = int(normalized[0])
            if number in (1, 9):
                danger -= 0.2
            elif number in (2, 8):
                danger += 0.1
            elif number in (4, 5, 6):
                danger += 0.4

            visible = self.visible_counts[tile_to_index(normalized)]
            if visible >= 3:
                danger -= 0.5
            elif visible == 2:
                danger -= 0.2
        return max(0.0, round(danger, 1))

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
        options = recommend_discards(self.hand, self.dora_indicators, self.open_melds, self.visible_counts)
        if self.riichi_seats:
            options.sort(
                key=lambda item: (
                    item["shanten"],
                    self.tile_danger_score(item["tile"]) * (2 if self.defensive_pressure() >= 3 else 1),
                    -item["ukeire"],
                    tile_sort_key(item["tile"]),
                )
            )
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
                "danger": self.tile_danger_score(item["tile"]) if self.riichi_seats else 0.0,
                "improving": item["improving"][:10],
                "improving_display": [display_tile(tile) for tile in item["improving"][:10]],
            })
        if best:
            snapshot["rule_recommendation"] = best["tile"]
            snapshot["rule_recommendation_display"] = display_tile(best["tile"])
            snapshot["confidence"] = self.recommendation_confidence(options)
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
        if self.defensive_pressure() >= 5 and best["shanten"] > 0 and safe_tiles:
            return True
        if self.is_all_last() and score_ctx.get("place") == 1 and safe_tiles and best["shanten"] > 0:
            return True
        if best["shanten"] >= 2 and self.tile_danger_score(best["tile"]) >= 1.6 and safe_tiles:
            return True
        return False

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
            )
            if not options:
                continue
            candidate = options[0].copy()
            candidate["combo"] = combo
            if (
                best is None
                or candidate["shanten"] < best["shanten"]
                or (candidate["shanten"] == best["shanten"] and candidate["ukeire"] > best["ukeire"])
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
                "reason": f"可碰 {display_tile(called_tile)}，是役牌/风牌碰牌，速度和打点都不差；保守建议可以碰。",
            }
        if best["shanten"] == current_shanten and best["ukeire"] > current_ukeire + 4:
            return {
                "action": label,
                "recommended": True,
                "target_tile": called_tile,
                "target_tile_display": display_tile(called_tile) if called_tile else None,
                "combination": best.get("combo"),
                "followup_discard": best["tile"],
                "followup_discard_display": display_tile(best["tile"]),
                "reason": f"可 {label} {display_tile(called_tile)}，向听不变但鸣后更快，优先切 {display_tile(best['tile'])}。",
            }
        return {
            "action": label,
            "recommended": False,
            "target_tile": called_tile,
            "target_tile_display": display_tile(called_tile) if called_tile else None,
            "combination": best.get("combo"),
            "followup_discard": best["tile"],
            "followup_discard_display": display_tile(best["tile"]),
            "reason": f"不建议 {label} {display_tile(called_tile)}，鸣后收益一般，先门清前进更稳。",
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
            for info in infos:
                wait_tile = info.get("tile")
                if not wait_tile:
                    continue
                waits.append(wait_tile)
                remaining = max(0, 4 - self.visible_counts[tile_to_index(wait_tile)])
                live += remaining
                has_yaku = has_yaku or bool(info.get("haveyi"))
                max_han = max(max_han, safe_int(info.get("count", 0)))
            if waits:
                options.append({
                    "discard": discard_tile,
                    "zhenting": zhenting,
                    "waits": waits,
                    "live": live,
                    "max_han": max_han,
                    "has_yaku": has_yaku,
                })
        options.sort(key=lambda item: (item["zhenting"], -item["live"], -item["max_han"]))
        return options

    def build_riichi_advice(self, data):
        options = self.evaluate_tenpai_options(data)
        if not options:
            return None

        best = options[0]
        best_desc = (
            f"最佳听牌: 打{display_tile(best['discard'])}听 {format_waits(best['waits'])} "
            f"(场上可见后剩 {best['live']} 枚)"
        )

        if best["zhenting"]:
            return f"{best_desc}。当前振听，不建议立直。"

        if not self.open_melds:
            if best["live"] >= 5 and best["max_han"] <= 2:
                return f"{best_desc}。建议立直：待牌不差，门清收益更高。"
            if best["live"] <= 2 and best["max_han"] >= 3:
                return f"{best_desc}。更建议默听：待牌少，但已有足够打点。"
            if best["live"] <= 2:
                return f"{best_desc}。待牌偏少，保守建议先默听。"
            if best["max_han"] >= 4:
                return f"{best_desc}。打点已经不低，偏向默听。"
            return f"{best_desc}。默认建议立直。"

        if best["has_yaku"]:
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
        confidence = self.recommendation_confidence(options)
        parts = [
            f"推荐切 {display_tile(best['tile'])}",
            f"向听={best['shanten']}",
            f"进张={best['ukeire']}",
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
            parts.append(f"场压={self.pressure_label()}")
        if best["improving"]:
            parts.append(f"改良={','.join(display_tile(tile) for tile in best['improving'][:8])}")
        lines = [" | ".join(parts)]
        if alts:
            alt_text = "；".join(
                (
                    f"{display_tile(item['tile'])} (向听{item['shanten']}, 进张{item['ukeire']}"
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
        if self.riichi_seats and best_danger >= 2.0 and best["shanten"] > 0:
            lines.append("防守提示: 场上已有立直，当前推荐牌仍偏危险；如果有现物/字牌安牌，优先考虑撤退。")
        if self.defensive_pressure() >= 4 and best["shanten"] > 0:
            lines.append("押退提示: 多家威胁或后巡，当前更应重视安全度，不建议为一般进张强押。")
        if score_ctx and score_ctx["place"] == 4 and score_ctx["top_gap"] > 12000 and best["shanten"] <= 1:
            lines.append("点况提示: 当前落后较多，必要时可以比平时更积极一些。")
        if self.is_all_last() and score_ctx:
            if score_ctx["place"] == 1 and score_ctx["last_gap"] > 4000:
                lines.append("收支提示: 终局领先，当前优先守住顺位，不值得为一般牌效冒险。")
            elif score_ctx["place"] == 4:
                lines.append("收支提示: 终局落后，允许比平时更积极，优先保留逆转路线。")
        if tilt == "积极" and best["shanten"] <= 1 and best_danger <= 1.6:
            lines.append("局况提示: 当前更需要争取和牌，若不是明显危险牌，可以适度继续进攻。")
        if tilt == "保守" and self.riichi_seats and best_danger >= 1.2:
            lines.append("局况提示: 当前分数和局况更适合守成，这类牌不值得为普通进张去押。")
        if confidence < 0.55:
            lines.append("不确定性提示: 这手规则判断优势不大，适合导出摘要后再问模型。")
        return "\n".join(lines)

    def effective_hand_tiles(self):
        return len(self.hand) + self.open_melds * 3

    def can_offer_discard_suggestion(self):
        return self.hand_seeded and self.effective_hand_tiles() >= 14

    def apply_action(self, action, event_index):
        self.event_index = event_index
        name = action.get("name")
        data = action.get("data")
        output = None
        self.last_action_plan = None

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
            self.riichi_seats = set()
            self.open_melds_by_seat = {seat: 0 for seat in range(4)}
            self.melds_by_seat = {seat: [] for seat in range(4)}
            self.current_scores = list(data.get("scores") or [])
            self.left_tile_count = data.get("left_tile_count")
            self.add_visible_tiles(self.dora_indicators)
            self.open_melds = 0
            self.last_suggestion_key = None
            if len(self.hand) == 14:
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
                if self.hand_seeded:
                    output = self.build_suggestion(f"自摸 {display_tile(tile) if tile else '?'}")
                    tenpai_advice = self.build_tenpai_advice(data)
                    if tenpai_advice:
                        output = f"{output}\n{tenpai_advice}"
                    riichi_advice = self.build_riichi_advice(data)
                    if riichi_advice:
                        output = f"{output}\n{riichi_advice}"
                    if output is None:
                        output = f"[live] 已识别到你的自摸 {display_tile(tile) if tile else '?'}，但本次建议被去重/状态条件跳过。"
                elif tile:
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
            if tile:
                self.add_visible_tile(tile)
            if data.get("is_liqi") and seat is not None:
                self.riichi_seats.add(seat)
            self.last_deal_seat = None
            self.last_discard_data = data
            op_notice = self.build_operation_notice(data)
            if op_notice:
                output = op_notice

        elif name == "ActionChiPengGang" and isinstance(data, dict):
            self.apply_public_call_visibility(data)
            self.apply_self_call(data)
            self.pending_self_call = None
            if data.get("seat") == self.self_seat and self.can_offer_discard_suggestion():
                output = self.build_suggestion(action_call_type_label(data.get("type")))
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
                outputs.append((index, suggestion))

    return len(messages), outputs


def run_once(path):
    total_messages, outputs = parse_har_actions(path)
    print(f"HAR: {path}")
    print(f"Messages: {total_messages}")
    print("")
    for index, suggestion in outputs:
        print(f"[msg {index:04d}]")
        print(suggestion)
        print("")


def run_watch(path, interval):
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
            if message_count < last_message_count:
                last_output_index = -1
            for index, suggestion in outputs:
                if index <= last_output_index:
                    continue
                print("")
                print(f"[msg {index:04d}]")
                print(suggestion)
                last_output_index = index
            last_message_count = message_count
            last_mtime = stat.st_mtime
            last_count = stat.st_size
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="Majsoul live helper based on exported HAR data.")
    parser.add_argument("har", help="Path to HAR file")
    parser.add_argument("--watch", action="store_true", help="Poll the HAR file and print new suggestions")
    parser.add_argument("--interval", type=float, default=2.0, help="Watch polling interval in seconds")
    args = parser.parse_args()

    if args.watch:
        run_watch(args.har, args.interval)
    else:
        run_once(args.har)


if __name__ == "__main__":
    main()
