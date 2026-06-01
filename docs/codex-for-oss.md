# Codex for Open Source Application Notes

This repository can be submitted to Codex for Open Source once the maintainer profile and repository are public. The strongest application angle is not broad adoption yet, but clear project specificity and active maintenance.

## Repository Qualification Draft

`mj_helper` is an open-source local Mahjong Soul live assistant. It decodes Mahjong Soul websocket/protobuf traffic through Chrome DevTools, maintains a four-player riichi Mahjong state machine, and gives real-time discard, call, riichi, and push/fold suggestions. The project also includes replay-based evaluation against exported game records and MAKA/Seer-aligned analysis data, making it useful for reproducible rule tuning rather than one-off prompting.

## API Credit Usage Draft

Use Codex/API credits to maintain the rule engine, review decision-rule pull requests, generate focused regression tests from replay mismatches, summarize MAKA/Seer-aligned evaluation deltas, and automate release-quality checks for parser, state-machine, and recommendation changes.

## Signals To Strengthen Before Applying

- Keep `README.md` runnable from a fresh clone with relative paths.
- Publish a license, contributing guide, and security/data-handling notes.
- Add one or two small sanitized replay fixtures so tests do not depend on private local data.
- Add screenshots or short terminal examples of live recommendations.
- Cut tagged releases after meaningful decision-quality improvements.
- Collect public usage signals: stars, issues, discussions, user feedback, or forks.
