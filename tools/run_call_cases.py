#!/usr/bin/env python3

import json
from pathlib import Path

from regression_common import build_state, print_assert


def main():
    case_path = Path(__file__).with_name("call_cases.json")
    cases = json.loads(case_path.read_text(encoding="utf-8"))
    failed = 0
    for case in cases:
        state = build_state(case["state"])
        plan = state.build_call_plan(case["op_type"], case["combinations"], case["called_tile"])
        expect = case["expect"]
        print(f"[{case['name']}] {case['description']}")
        print(f"  result: recommended={plan.get('recommended')} followup={plan.get('followup_discard')} reason={plan.get('reason')}")
        failed += print_assert("recommended", plan.get("recommended") == expect["recommended"], f"{plan.get('recommended')} == {expect['recommended']}")
        failed += print_assert("followup_discard", plan.get("followup_discard") == expect["followup_discard"], f"{plan.get('followup_discard')} == {expect['followup_discard']}")
        print("")
    if failed:
        raise SystemExit(f"{failed} call expectation(s) failed")
    print("All call expectations passed.")


if __name__ == "__main__":
    main()
