#!/usr/bin/env python3

import json
from pathlib import Path

from regression_common import build_state, print_assert


def main():
    case_path = Path(__file__).with_name("push_fold_cases.json")
    cases = json.loads(case_path.read_text(encoding="utf-8"))
    failed = 0
    for case in cases:
        state = build_state(case["state"])
        options = state.evaluate_discard_options()
        best = options[0]
        decision = state.last_push_fold_decision or {}
        expect = case["expect"]
        print(f"[{case['name']}] {case['description']}")
        print(f"  result: mode={decision.get('mode')} goal={decision.get('goal')} tile={best['tile']}")
        failed += print_assert("mode", decision.get("mode") == expect["mode"], f"{decision.get('mode')} == {expect['mode']}")
        failed += print_assert("goal", decision.get("goal") == expect["goal"], f"{decision.get('goal')} == {expect['goal']}")
        failed += print_assert("tile", best["tile"] == expect["tile"], f"{best['tile']} == {expect['tile']}")
        print("")
    if failed:
        raise SystemExit(f"{failed} push/fold expectation(s) failed")
    print("All push/fold expectations passed.")


if __name__ == "__main__":
    main()
