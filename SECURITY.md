# Security Policy

This project runs locally and connects to a user-controlled Chrome DevTools debugging port. It should not be exposed on a public network.

## Reporting Issues

Please open a GitHub issue if you find a security or privacy problem, and avoid posting private replay logs, account identifiers, cookies, or browser debugging output in public.

## Data Handling

- Do not commit `live_debug*.jsonl`, replay exports, browser profiles, or third-party analysis reports.
- Review captured websocket/debug output before sharing it, because it may contain account or session metadata.
- Prefer reduced test fixtures that preserve only the fields needed to reproduce a decision.
