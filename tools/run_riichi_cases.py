#!/usr/bin/env python3

import json
from pathlib import Path

from regression_common import build_state, print_assert


def main():
    case_path = Path(__file__).with_name("riichi_cases.json")
    cases = json.loads(case_path.read_text(encoding="utf-8"))
    failed = 0
    for case in cases:
        state = build_state(case["state"])
        advice = state.build_riichi_advice(case["data"])
        analysis = state.last_tenpai_analysis or {}
        expect = case["expect"]
        print(f"[{case['name']}] {case['description']}")
        print(f"  result: template={analysis.get('decision_template')} advice={advice}")
        failed += print_assert(
            "decision_template",
            analysis.get("decision_template") == expect["decision_template"],
            f"{analysis.get('decision_template')} == {expect['decision_template']}",
        )
        print("")
    if failed:
        raise SystemExit(f"{failed} riichi expectation(s) failed")
    print("All riichi expectations passed.")


if __name__ == "__main__":
    main()
