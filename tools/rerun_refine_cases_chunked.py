#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from pathlib import Path


def load_case_count(path: Path) -> int:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return len(payload.get("cases") or [])


def main():
    parser = argparse.ArgumentParser(description="Run refine reruns in subprocess chunks to cap memory growth.")
    parser.add_argument("cases_json")
    parser.add_argument("--player-name", default="Levey")
    parser.add_argument("--lookahead-limit", type=int, default=2)
    parser.add_argument("--include-aux-advice", action="store_true")
    parser.add_argument("--snapshot-jsonl", required=True)
    parser.add_argument("--summary-dir", required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int)
    parser.add_argument("--chunk-size", type=int, default=20)
    parser.add_argument("--append", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()

    cases_path = Path(args.cases_json)
    total_count = load_case_count(cases_path)
    end = total_count if args.end is None else min(args.end, total_count)
    start = max(0, min(args.start, end))

    summary_dir = Path(args.summary_dir)
    summary_dir.mkdir(parents=True, exist_ok=True)

    chunk_starts = list(range(start, end, args.chunk_size))
    if not chunk_starts:
        print("[chunked-refine] nothing to run")
        return

    append_mode = args.append
    for chunk_start in chunk_starts:
        chunk_limit = min(args.chunk_size, end - chunk_start)
        chunk_end = chunk_start + chunk_limit
        summary_path = summary_dir / f"summary_{chunk_start:03d}_{chunk_end:03d}.json"
        cmd = [
            sys.executable,
            str(Path(__file__).with_name("rerun_refine_cases.py")),
            str(cases_path),
            "--player-name",
            args.player_name,
            "--lookahead-limit",
            str(args.lookahead_limit),
            "--snapshot-jsonl",
            args.snapshot_jsonl,
            "--summary-json",
            str(summary_path),
            "--start",
            str(chunk_start),
            "--limit",
            str(chunk_limit),
        ]
        if args.include_aux_advice:
            cmd.append("--include-aux-advice")
        if append_mode:
            cmd.append("--append")
        if args.skip_existing:
            cmd.append("--skip-existing")

        print(
            f"[chunked-refine] chunk {chunk_start}:{chunk_end} -> {summary_path.name}",
            flush=True,
        )
        subprocess.run(cmd, check=True)
        append_mode = True

    print(f"[chunked-refine] completed range {start}:{end}")
    print(f"[chunked-refine] snapshots: {args.snapshot_jsonl}")
    print(f"[chunked-refine] summaries: {summary_dir}")


if __name__ == "__main__":
    main()
