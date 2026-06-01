#!/usr/bin/env python3

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RUNNERS = [
    "run_danger_cases.py",
    "run_push_fold_cases.py",
    "run_call_cases.py",
    "run_riichi_cases.py",
]


def main():
    failed = []
    for runner in RUNNERS:
        path = ROOT / runner
        print(f"== Running {runner} ==")
        result = subprocess.run([sys.executable, str(path)], cwd=str(ROOT.parent))
        print("")
        if result.returncode != 0:
            failed.append(runner)
    if failed:
        print("Regression summary: FAIL")
        for runner in failed:
            print(f"  - {runner}")
        raise SystemExit(1)
    print("Regression summary: PASS")


if __name__ == "__main__":
    main()
