# Contributing

Thanks for helping improve the Mahjong Soul live helper. The project is still early, so the most useful contributions are small, reproducible, and backed by replay or regression evidence.

## Good First Contributions

- Add a reduced replay case for a wrong discard, call, riichi, or push/fold recommendation.
- Improve documentation for setup, replay analysis, or evaluation.
- Add regression cases under `tools/*_cases.json` when a decision rule changes.
- Refactor a narrow decision helper when tests prove behavior stayed stable.

## Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

## Verification

Run the focused unit tests before sending a change:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/mj_pycache \
python3 -m unittest test_majsoul_live_helper.py
```

For decision-rule changes, also run the lightweight regression suite when the local case files are available:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/mj_pycache \
python3 tools/run_all_regressions.py
```

## Pull Request Notes

Please include:

- What user-visible decision changed.
- A replay, test case, or minimal hand state that demonstrates the issue.
- Before/after output for the affected recommendation when possible.

Avoid committing local replay exports, debug logs, browser profiles, or third-party report dumps.
