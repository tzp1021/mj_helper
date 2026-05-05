import json
import unittest
import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ARCHIVE_TOOLS = ROOT / "tools" / "archive"
if str(ARCHIVE_TOOLS) not in sys.path:
    sys.path.insert(0, str(ARCHIVE_TOOLS))

from majsoul_live_helper import (
    LiveGameState,
    load_manifest_index,
    record_accounts_mapping,
    recommend_discards,
    tile_to_index,
    wait_shape_score,
)
from compare_with_seer import seer_action_to_tile, seer_recommend_seat
from review_discard_overrides import classify_override
from review_riichi_thresholds import classify_riichi_case
from review_operation_thresholds import classify_case


class RecommendDiscardsTest(unittest.TestCase):
    def test_discards_isolated_honor_before_dora_shape(self):
        tiles = ["1z", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "2p", "3p", "4p", "5s", "5s", "9s"]
        options = recommend_discards(tiles, ["4m"])
        self.assertEqual(options[0]["tile"], "1z")
        self.assertGreater(options[0]["efficiency_score"], options[1]["efficiency_score"])

    def test_option_contains_future_progress_metrics(self):
        tiles = ["1m", "2m", "3m", "4m", "5m", "6m", "2p", "3p", "4p", "6p", "7p", "8p", "5z", "5z"]
        option = recommend_discards(tiles, [])[0]
        self.assertIn("advance_ukeire", option)
        self.assertIn("improvement_ukeire", option)
        self.assertIn("future_ukeire", option)
        self.assertGreaterEqual(option["improvement_ukeire"], 0)

    def test_discard_options_get_risk_reward_tags(self):
        state = LiveGameState()
        state.self_seat = 0
        state.chang = 0
        state.ju = 0
        state.hand = ["2m", "3m", "4m", "5m", "6m", "7m", "2p", "3p", "4p", "5p", "6p", "7p", "8p", "8p"]
        state.hand_seeded = True
        state.riichi_seats = {1}
        state.discards_by_seat = {1: ["1z", "4z", "7z"]}
        state.discard_meta_by_seat = {
            1: [{"tile": t, "event_index": i, "moqie": False, "is_liqi": i == 2} for i, t in enumerate(state.discards_by_seat[1])]
        }
        state.riichi_event_index = {1: 2}
        options = state.evaluate_discard_options()
        self.assertTrue(any(item.get("risk_reward_tags") for item in options))

    def test_discard_risk_weight_changes_with_push_template_and_tilt(self):
        state = LiveGameState()
        state.self_seat = 0
        item = {"shanten": 1, "risk_reward_tags": ["高总危险", "高打点路线"]}
        aggressive = state.risk_weight_for_option(item, pressure=4, tilt="积极")
        conservative = state.risk_weight_for_option(item, pressure=4, tilt="保守")
        self.assertLess(aggressive, conservative)

    def test_discard_safety_policy_prefers_safer_same_shanten_option(self):
        state = LiveGameState()
        state.riichi_seats = {1}
        state.chang = 1
        state.ju = 3
        state.current_scores = [32000, 25000, 22000, 21000]
        state.max_seat_danger = lambda tile: {"5p": 2.1, "1z": 0.6}[tile]
        options = [
            {"tile": "5p", "shanten": 1, "efficiency_score": 120.0, "risk_reward_tags": ["高总危险", "高打点路线"]},
            {"tile": "1z", "shanten": 1, "efficiency_score": 108.0, "risk_reward_tags": []},
        ]
        reordered = state.apply_discard_safety_policy(options, pressure=5, tilt="保守")
        self.assertEqual(reordered[0]["tile"], "1z")
        self.assertEqual(state.last_discard_policy_note["reason"], "same_shanten_safer_override")

    def test_discard_safety_policy_keeps_aggressive_tenpai_push(self):
        state = LiveGameState()
        state.riichi_seats = {1}
        state.max_seat_danger = lambda tile: {"5p": 2.1, "1z": 0.6}[tile]
        options = [
            {"tile": "5p", "shanten": 0, "efficiency_score": 120.0, "risk_reward_tags": ["高总危险", "高质量听牌"]},
            {"tile": "1z", "shanten": 0, "efficiency_score": 110.0, "risk_reward_tags": []},
        ]
        reordered = state.apply_discard_safety_policy(options, pressure=4, tilt="积极")
        self.assertEqual(reordered[0]["tile"], "5p")

    def test_discard_safety_policy_preserves_all_last_value_push(self):
        state = LiveGameState()
        state.self_seat = 0
        state.riichi_seats = {1}
        state.chang = 0
        state.ju = 3
        state.current_scores = [18000, 26000, 24000, 32000]
        state.max_seat_danger = lambda tile: {"5p": 2.3, "1z": 0.6}[tile]
        options = [
            {
                "tile": "5p",
                "shanten": 1,
                "efficiency_score": 120.0,
                "risk_reward_tags": ["高总危险", "高打点路线", "强一向听"],
            },
            {"tile": "1z", "shanten": 1, "efficiency_score": 111.0, "risk_reward_tags": []},
        ]
        reordered = state.apply_discard_safety_policy(options, pressure=5, tilt="积极")
        self.assertEqual(reordered[0]["tile"], "5p")
        self.assertEqual(state.last_discard_policy_note["reason"], "preserve_risky_push")
        self.assertEqual(state.last_discard_policy_note["preserve_reason"], "all_last_value_keep")
        self.assertIn("终局落后", state.discard_policy_note_text())

    def test_discard_safety_policy_preserves_value_route_push(self):
        state = LiveGameState()
        state.riichi_seats = {1}
        state.max_seat_danger = lambda tile: {"5p": 2.1, "1z": 0.6}[tile]
        options = [
            {"tile": "5p", "shanten": 1, "efficiency_score": 120.0, "risk_reward_tags": ["高总危险", "高打点路线"]},
            {"tile": "1z", "shanten": 1, "efficiency_score": 114.5, "risk_reward_tags": []},
        ]
        reordered = state.apply_discard_safety_policy(options, pressure=5, tilt="保守")
        self.assertEqual(reordered[0]["tile"], "5p")
        self.assertEqual(state.last_discard_policy_note["preserve_reason"], "value_route_keep")

    def test_suggestion_text_mentions_high_risk_high_value_push(self):
        state = LiveGameState()
        state.self_seat = 0
        state.chang = 0
        state.ju = 0
        state.hand = ["2m", "3m", "4m", "5m", "6m", "7m", "2p", "3p", "4p", "5p", "6p", "7p", "8p", "8p"]
        state.hand_seeded = True
        state.riichi_seats = {1}
        state.discards_by_seat = {1: ["1z", "4z", "7z"]}
        state.discard_meta_by_seat = {
            1: [{"tile": t, "event_index": i, "moqie": False, "is_liqi": i == 2} for i, t in enumerate(state.discards_by_seat[1])]
        }
        state.riichi_event_index = {1: 2}
        text = state.suggestion_text()
        self.assertIn("标签=", text)


class LiveGameStateAdviceTest(unittest.TestCase):
    def test_wait_shape_score_prefers_multi_sided_wait(self):
        self.assertGreater(wait_shape_score(["3m", "6m", "9m"]), wait_shape_score(["1m"]))
        self.assertGreater(wait_shape_score(["4m", "7m"]), wait_shape_score(["1m"]))

    def test_all_last_lead_prefers_damaten(self):
        state = LiveGameState()
        state.self_seat = 0
        state.chang = 0
        state.ju = 3
        state.current_scores = [32000, 27000, 22000, 19000]
        advice = state.build_riichi_advice({
            "tingpais": [
                {
                    "tile": "3m",
                    "zhenting": False,
                    "infos": [
                        {"tile": "6m", "haveyi": True, "count": 2},
                        {"tile": "9m", "haveyi": True, "count": 2},
                    ],
                }
            ]
        })
        self.assertIn("优先默听守顺位", advice)

    def test_dora_tile_is_more_dangerous_against_riichi(self):
        state = LiveGameState()
        state.riichi_seats = {1}
        state.discards_by_seat = {1: ["1m", "4m", "7m"]}
        state.dora_indicators = ["4m"]
        safe = state.tile_danger_score("3m")
        dangerous = state.tile_danger_score("5m")
        self.assertGreater(dangerous, safe)

    def test_hand_value_score_prefers_value_honor_over_nonvalue_honor(self):
        value_hand = ["6z", "2m", "3m", "4m", "2p", "3p", "4p", "6s", "7s", "8s", "1m", "9m", "5p"]
        plain_hand = ["4z", "2m", "3m", "4m", "2p", "3p", "4p", "6s", "7s", "8s", "1m", "9m", "5p"]
        from majsoul_live_helper import hand_value_score, hand_to_counts
        value_score = hand_value_score(hand_to_counts(value_hand), seat_wind="1z", round_wind="2z")
        plain_score = hand_value_score(hand_to_counts(plain_hand), seat_wind="1z", round_wind="2z")
        self.assertGreater(value_score, plain_score)

    def test_effective_safe_tiles_uses_most_dangerous_riichi_player(self):
        state = LiveGameState()
        state.hand = ["3m", "9m", "1z"]
        state.riichi_seats = {1, 2}
        state.discards_by_seat = {
            1: ["6m", "2p", "5p"],
            2: ["6m", "3s", "6s"],
        }
        state.discard_meta_by_seat = {
            1: [{"tile": t, "event_index": i, "moqie": False, "is_liqi": False} for i, t in enumerate(state.discards_by_seat[1])],
            2: [{"tile": t, "event_index": i, "moqie": False, "is_liqi": False} for i, t in enumerate(state.discards_by_seat[2])],
        }
        safe_tiles = state.effective_safe_tiles()
        self.assertIn("3m", safe_tiles)
        self.assertNotIn("1z", safe_tiles)
        self.assertGreater(state.tile_danger_score("3m"), 0.9)
        self.assertLessEqual(state.max_seat_danger("3m"), 0.9)

    def test_late_riichi_player_gets_higher_threat_weight(self):
        state = LiveGameState()
        state.ju = 0
        state.riichi_seats = {1, 2}
        state.riichi_event_index = {1: 10, 2: 20}
        state.discards_by_seat = {
            1: ["1m", "2m", "3m", "4m", "5m", "6m"],
            2: ["1p", "2p", "3p", "4p", "5p", "6p", "7p", "8p", "9p", "1s", "2s", "3s", "4s"],
        }
        self.assertLess(state.seat_threat_weight(1), state.seat_threat_weight(2))

    def test_aggressive_endgame_reduces_risk_weight_for_tenpai(self):
        state = LiveGameState()
        state.self_seat = 0
        state.chang = 1
        state.ju = 3
        state.current_scores = [18000, 26000, 24000, 32000]
        state.riichi_seats = {1}
        cautious = state.risk_weight_for_option({"shanten": 2}, pressure=4, tilt=state.strategic_tilt())
        tenpai = state.risk_weight_for_option({"shanten": 0}, pressure=4, tilt=state.strategic_tilt())
        self.assertLess(tenpai, cautious)

    def test_good_shape_low_value_prefers_riichi(self):
        state = LiveGameState()
        state.self_seat = 0
        advice = state.build_riichi_advice({
            "tingpais": [
                {
                    "tile": "3m",
                    "zhenting": False,
                    "infos": [
                        {"tile": "3m", "haveyi": True, "count": 1},
                        {"tile": "6m", "haveyi": True, "count": 1},
                        {"tile": "9m", "haveyi": True, "count": 1},
                    ],
                }
            ]
        })
        self.assertIn("建议立直", advice)
        self.assertEqual(state.last_tenpai_analysis["decision_template"], "good_shape_riichi")
        self.assertIn("立直补收益", state.last_tenpai_analysis["template_note"])

    def test_poor_shape_high_value_prefers_damaten(self):
        state = LiveGameState()
        state.self_seat = 0
        advice = state.build_riichi_advice({
            "tingpais": [
                {
                    "tile": "7p",
                    "zhenting": False,
                    "infos": [
                        {"tile": "1m", "haveyi": True, "count": 4, "point_rong": 12000},
                    ],
                }
            ]
        })
        self.assertTrue("偏向默听" in advice or "更建议默听" in advice)
        self.assertIn(state.last_tenpai_analysis["decision_template"], {"value_damaten", "high_value_damaten"})

    def test_dealer_riichi_template_is_recorded(self):
        state = LiveGameState()
        state.self_seat = 0
        state.ju = 0
        advice = state.build_riichi_advice({
            "tingpais": [
                {
                    "tile": "3m",
                    "zhenting": False,
                    "infos": [
                        {"tile": "3m", "haveyi": True, "count": 1},
                        {"tile": "6m", "haveyi": True, "count": 1},
                        {"tile": "9m", "haveyi": True, "count": 1},
                    ],
                }
            ]
        })
        self.assertIn("建议立直", advice)
        self.assertEqual(state.last_tenpai_analysis["decision_template"], "dealer_riichi")
        self.assertIn("亲家好形听牌", state.last_tenpai_analysis["template_note"])

    def test_value_honor_peng_is_preferred(self):
        state = LiveGameState()
        state.self_seat = 0
        state.chang = 0
        state.ju = 0
        state.hand = ["1z", "1z", "2m", "3m", "4m", "3p", "4p", "5p", "6s", "7s", "8s", "2p", "9m"]
        state.hand_seeded = True
        plan = state.build_call_plan(3, ["1z|1z"], "1z")
        self.assertTrue(plan["recommended"])
        self.assertIn("向听从 1 压到 0", plan["reason"])
        self.assertIn("鸣入役牌东", plan["yaku_tags"])

    def test_call_is_rejected_when_it_breaks_defense_under_riichi(self):
        state = LiveGameState()
        state.self_seat = 0
        state.chang = 0
        state.ju = 0
        state.hand = ["3m", "4m", "1z", "1z", "2p", "3p", "4p", "6s", "7s", "8s", "5m", "6m", "9p"]
        state.hand_seeded = True
        state.riichi_seats = {1}
        state.discards_by_seat = {1: ["1z", "4z", "7z"]}
        state.discard_meta_by_seat = {
            1: [{"tile": t, "event_index": i, "moqie": False, "is_liqi": i == 2} for i, t in enumerate(state.discards_by_seat[1])]
        }
        state.riichi_event_index = {1: 2}
        plan = state.build_call_plan(2, ["3m|4m"], "2m")
        self.assertFalse(plan["recommended"])
        self.assertIn("优先保留退路", plan["reason"])
        self.assertGreater(plan["call_breakdown"]["danger_loss"], 0.0)

    def test_same_shanten_dangerous_call_is_blocked_under_riichi(self):
        state = LiveGameState()
        state.self_seat = 0
        state.chang = 0
        state.ju = 1
        state.current_scores = [25000, 25000, 25000, 25000]
        state.hand = ["3m", "4m", "5m", "6m", "7m", "8m", "2p", "3p", "5p", "6p", "7p", "8p", "9p"]
        state.hand_seeded = True
        state.riichi_seats = {1}
        state.discards_by_seat = {1: ["1z", "4z", "7z"]}
        state.discard_meta_by_seat = {
            1: [{"tile": t, "event_index": i, "moqie": False, "is_liqi": i == 2} for i, t in enumerate(state.discards_by_seat[1])]
        }
        state.riichi_event_index = {1: 2}
        plan = state.build_call_plan(2, ["3m|4m"], "2m")
        self.assertFalse(plan["recommended"])
        self.assertIn("放铳风险", plan["reason"])

    def test_open_yaku_profile_marks_tanyao_and_flush_bias(self):
        state = LiveGameState()
        state.self_seat = 0
        counts = [0] * 34
        for tile in ["2m", "3m", "4m", "4m", "5m", "6m", "6m", "7m", "8m"]:
            counts[tile_to_index(tile)] += 1
        profile = state.open_yaku_profile(counts, "5m")
        self.assertGreater(profile["score"], 1.0)
        self.assertIn("断幺", profile["tags"])
        self.assertTrue(any(tag in profile["tags"] for tag in ("染手", "一色寄り")))

    def test_aggressive_same_shanten_call_can_be_recommended(self):
        state = LiveGameState()
        state.self_seat = 0
        state.chang = 1
        state.ju = 3
        state.current_scores = [18000, 26000, 24000, 32000]
        state.hand = ["3m", "4m", "5m", "6m", "7m", "8m", "2p", "3p", "4p", "4p", "5p", "6p", "7p"]
        state.hand_seeded = True
        plan = state.build_call_plan(2, ["3m|4m"], "2m")
        self.assertTrue(plan["recommended"])
        self.assertTrue(
            "综合路线已经明显优于门清" in plan["reason"]
            or "典型高价值副露形" in plan["reason"]
            or "典型断幺/一色寄副露路线" in plan["reason"]
        )
        self.assertIn("断幺", plan["yaku_tags"])
        self.assertGreater(plan["call_breakdown"]["tenpai_bonus"], 0.0)

    def test_neutral_same_shanten_high_route_call_can_be_recommended(self):
        state = LiveGameState()
        state.self_seat = 0
        state.chang = 0
        state.ju = 1
        state.current_scores = [25000, 25000, 25000, 25000]
        state.hand = ["3m", "4m", "5m", "6m", "7m", "8m", "2p", "3p", "4p", "4p", "5p", "6p", "7p"]
        state.hand_seeded = True
        plan = state.build_call_plan(2, ["3m|4m"], "2m")
        self.assertTrue(plan["recommended"])
        self.assertTrue(
            "综合路线已经明显优于门清" in plan["reason"]
            or "典型高价值副露形" in plan["reason"]
            or "典型断幺/一色寄副露路线" in plan["reason"]
        )
        self.assertGreaterEqual(plan["call_breakdown"]["tenpai_bonus"], 2.4)

    def test_same_shanten_gate_reports_aggressive_push(self):
        state = LiveGameState()
        state.self_seat = 0
        state.chang = 1
        state.ju = 3
        state.current_scores = [18000, 26000, 24000, 32000]
        state.hand = ["3m", "4m", "5m", "6m", "7m", "8m", "2p", "3p", "4p", "4p", "5p", "6p", "7p"]
        state.hand_seeded = True
        plan = state.build_call_plan(2, ["3m|4m"], "2m")
        allowed, reason = state.should_allow_same_shanten_call({
            "tile": plan["followup_discard"],
            "shanten": 0,
            "call_score": plan["call_score"],
            "call_breakdown": plan["call_breakdown"],
            "yaku_profile": {"score": plan["open_yaku_potential"]},
        })
        self.assertTrue(allowed)
        self.assertIn(reason, {"aggressive_push", "route_push"})

    def test_riichi_exception_requires_high_bonus_and_low_danger(self):
        state = LiveGameState()
        state.riichi_seats = {1}
        state.discards_by_seat = {1: ["2m"]}
        allowed, reason = state.should_allow_same_shanten_call({
            "tile": "2m",
            "call_score": 9.3,
            "call_breakdown": {"tenpai_bonus": 4.5, "danger_loss": 0.9},
            "yaku_profile": {"score": 1.8},
        })
        self.assertTrue(allowed)
        self.assertEqual(reason, "riichi_exception")

        blocked, blocked_reason = state.should_allow_same_shanten_call({
            "tile": "2m",
            "call_score": 9.3,
            "call_breakdown": {"tenpai_bonus": 4.5, "danger_loss": 1.2},
            "yaku_profile": {"score": 1.8},
        })
        self.assertFalse(blocked)
        self.assertIn(blocked_reason, {"riichi_block", "danger_block"})

    def test_review_threshold_classifier(self):
        self.assertEqual(classify_case({"call_score": 7.5, "yaku_gain": 4.6, "tenpai_bonus": 2.7, "danger_loss": 0.8}), "likely_release")
        self.assertEqual(classify_case({"call_score": 5.3, "yaku_gain": 4.8, "tenpai_bonus": 0.0, "danger_loss": 2.1}), "reasonable_reject")

    def test_discard_override_classifier_prefers_explicit_bucket(self):
        bucket = classify_override(
            {"reason": "same_shanten_safer_override", "bucket": "value_push_overridden"},
            {"danger": 2.8, "risk_reward_tags": ["高总危险", "高打点路线"]},
        )
        self.assertEqual(bucket, "value_push_overridden")

    def test_riichi_review_classifier_flags_borderline_cases(self):
        self.assertEqual(
            classify_riichi_case({"decision_template": "threat_riichi_check", "push_value": 3.8}),
            "damaten_recheck",
        )
        self.assertEqual(
            classify_riichi_case({"decision_template": "default_riichi", "push_value": 3.5}),
            "riichi_borderline",
        )

    def test_seer_action_tile_mapping_and_default_seat(self):
        self.assertEqual(seer_action_to_tile(111), "1m")
        self.assertEqual(seer_action_to_tile(128), "8p")
        self.assertEqual(seer_action_to_tile(147), "7z")
        self.assertIsNone(seer_action_to_tile(5))
        self.assertEqual(seer_recommend_seat({}), 0)
        self.assertEqual(seer_recommend_seat({"seat": 3}), 3)

    def test_load_manifest_index_supports_pairs_shape(self):
        payload = {
            "count": 1,
            "pairs": [
                {"uuid": "abc", "players": ["Levey"]},
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "manifest.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            index = load_manifest_index(path)
        self.assertIn("abc", index)
        self.assertEqual(index["abc"]["players"], ["Levey"])

    def test_record_accounts_mapping_prefers_record_head_seats(self):
        record = {
            "head": {
                "accounts": [
                    {"seat": 2, "nickname": "Alice"},
                    {"seat": 1, "nickname": "Levey"},
                    {"seat": 3, "nickname": "Bob"},
                ]
            }
        }
        self.assertEqual(record_accounts_mapping(record), {2: "Alice", 1: "Levey", 3: "Bob"})

    def test_call_rejection_template_matches_reasonable_reject_modes(self):
        state = LiveGameState()
        self.assertEqual(state.call_rejection_template({"call_breakdown": {"danger_loss": 2.1}}), "high_danger_loss")
        self.assertEqual(state.call_rejection_template({"call_breakdown": {"danger_loss": 1.3, "tenpai_bonus": 1.2}}), "danger_over_speed")
        self.assertEqual(state.call_rejection_template({"call_breakdown": {"danger_loss": 0.8, "yaku_gain": 3.5, "tenpai_bonus": 1.0}}), "weak_value_path")

    def test_same_shanten_gate_supports_pattern_release(self):
        state = LiveGameState()
        allowed, reason = state.should_allow_same_shanten_call({
            "tile": "2m",
            "call_score": 6.8,
            "call_breakdown": {"tenpai_bonus": 2.6, "danger_loss": 0.8, "yaku_gain": 3.6},
            "yaku_profile": {"score": 1.7, "tags": ["断幺", "一色寄り"]},
        })
        self.assertTrue(allowed)
        self.assertEqual(reason, "pattern_release")

    def test_same_shanten_gate_denies_pattern_release_when_danger_high(self):
        state = LiveGameState()
        blocked, reason = state.should_allow_same_shanten_call({
            "tile": "2m",
            "call_score": 6.8,
            "call_breakdown": {"tenpai_bonus": 2.6, "danger_loss": 1.3, "yaku_gain": 3.6},
            "yaku_profile": {"score": 1.7, "tags": ["断幺", "一色寄り"]},
        })
        self.assertFalse(blocked)
        self.assertEqual(reason, "default_block")

    def test_same_shanten_gate_supports_chi_pattern_release(self):
        state = LiveGameState()
        allowed, reason = state.should_allow_same_shanten_call({
            "tile": "2m",
            "call_score": 7.0,
            "call_breakdown": {"tenpai_bonus": 3.0, "danger_loss": 0.7, "yaku_gain": 3.6},
            "yaku_profile": {"score": 1.7, "tags": ["断幺", "一色寄り"]},
        }, op_type=2)
        self.assertTrue(allowed)
        self.assertEqual(reason, "chi_pattern_release")

    def test_same_shanten_gate_blocks_chi_pattern_release_when_danger_high(self):
        state = LiveGameState()
        blocked, reason = state.should_allow_same_shanten_call({
            "tile": "2m",
            "call_score": 7.0,
            "call_breakdown": {"tenpai_bonus": 3.0, "danger_loss": 1.1, "yaku_gain": 3.6},
            "yaku_profile": {"score": 1.7, "tags": ["断幺", "一色寄り"]},
        }, op_type=2)
        self.assertFalse(blocked)
        self.assertEqual(reason, "default_block")

    def test_same_shanten_gate_supports_peng_pattern_release(self):
        state = LiveGameState()
        allowed, reason = state.should_allow_same_shanten_call({
            "tile": "2p",
            "call_score": 6.8,
            "call_breakdown": {"tenpai_bonus": 2.5, "danger_loss": 0.7, "yaku_gain": 4.0},
            "yaku_profile": {"score": 2.0, "tags": ["役牌对东", "鸣入役牌东"]},
        }, op_type=3)
        self.assertTrue(allowed)
        self.assertEqual(reason, "peng_pattern_release")

    def test_same_shanten_gate_supports_peng_tenpai_release(self):
        state = LiveGameState()
        allowed, reason = state.should_allow_same_shanten_call({
            "tile": "2p",
            "call_score": 7.3,
            "call_breakdown": {"tenpai_bonus": 3.3, "danger_loss": 0.7, "yaku_gain": 4.1},
            "yaku_profile": {"score": 2.1, "tags": ["役牌对东", "鸣入役牌东"]},
        }, op_type=3)
        self.assertTrue(allowed)
        self.assertEqual(reason, "peng_tenpai_release")

    def test_same_shanten_gate_blocks_peng_pattern_release_when_danger_high(self):
        state = LiveGameState()
        blocked, reason = state.should_allow_same_shanten_call({
            "tile": "2p",
            "call_score": 6.8,
            "call_breakdown": {"tenpai_bonus": 2.5, "danger_loss": 1.1, "yaku_gain": 4.0},
            "yaku_profile": {"score": 2.0, "tags": ["役牌对东", "鸣入役牌东"]},
        }, op_type=3)
        self.assertFalse(blocked)
        self.assertEqual(reason, "default_block")


if __name__ == "__main__":
    unittest.main()
