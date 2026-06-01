#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path("/Users/bigo/code/mj")
TOOLS = ROOT / "tools"
ARCHIVE = ROOT / "data" / "archive"
TENHOU = ROOT / "data" / "tenhou"


def run(cmd):
    print("[pipeline]", " ".join(str(x) for x in cmd), flush=True)
    subprocess.run([str(x) for x in cmd], check=True)


def main():
    parser = argparse.ArgumentParser(
        description="Run full low-memory Tenhou replay pipeline for one mjlog dataset."
    )
    parser.add_argument("dataset", help="e.g. mjlog4")
    parser.add_argument("--player-name", default="Levey")
    parser.add_argument("--fast-lookahead", type=int, default=0)
    parser.add_argument("--refine-lookahead", type=int, default=2)
    parser.add_argument("--fast-chunk-size", type=int, default=5)
    parser.add_argument("--refine-chunk-size", type=int, default=10)
    parser.add_argument("--refine-limit", type=int, default=500)
    parser.add_argument("--refine-max-per-source", type=int, default=2)
    args = parser.parse_args()

    dataset = args.dataset
    mjlog_dir = TENHOU / dataset
    if not mjlog_dir.exists():
        raise SystemExit(f"missing dataset dir: {mjlog_dir}")

    valid_manifest = ARCHIVE / f"valid_tenhou_{dataset}_manifest.json"
    invalid_manifest = ARCHIVE / f"invalid_tenhou_{dataset}_manifest.json"
    fast_jsonl = ARCHIVE / f"tenhou_{dataset}_fast.jsonl"
    fast_normalized_jsonl = ARCHIVE / f"tenhou_{dataset}_fast.normalized.jsonl"
    fast_summary_dir = ARCHIVE / f"tenhou_{dataset}_fast_summaries"
    refine_cases = ARCHIVE / f"tenhou_{dataset}_refine_cases.json"
    refined_jsonl = ARCHIVE / f"tenhou_{dataset}_refined.jsonl"
    refine_summary_dir = ARCHIVE / f"tenhou_{dataset}_refine_summaries"
    compare_json = ARCHIVE / f"tenhou_{dataset}_refine_compare.json"
    change_summary = ARCHIVE / f"tenhou_{dataset}_refine_change_summary.json"
    cluster_json = ARCHIVE / f"tenhou_{dataset}_refine_cluster_report.json"
    cluster_md = ARCHIVE / f"tenhou_{dataset}_refine_cluster_report.md"

    run(
        [
            sys.executable,
            TOOLS / "build_valid_tenhou_manifest.py",
            "--mjlog-dir",
            mjlog_dir,
            "--valid-output",
            valid_manifest,
            "--invalid-output",
            invalid_manifest,
        ]
    )

    if fast_jsonl.exists():
        fast_jsonl.unlink()
    if fast_normalized_jsonl.exists():
        fast_normalized_jsonl.unlink()
    if refined_jsonl.exists():
        refined_jsonl.unlink()

    fast_summary_dir.mkdir(parents=True, exist_ok=True)
    refine_summary_dir.mkdir(parents=True, exist_ok=True)

    run(
        [
            sys.executable,
            TOOLS / "replay_paipu_chunked.py",
            valid_manifest,
            "--player-name",
            args.player_name,
            "--snapshot-jsonl",
            fast_jsonl,
            "--summary-dir",
            fast_summary_dir,
            "--lookahead-limit",
            str(args.fast_lookahead),
            "--chunk-size",
            str(args.fast_chunk_size),
        ]
    )

    run(
        [
            sys.executable,
            TOOLS / "normalize_replay_jsonl.py",
            fast_jsonl,
            "--output",
            fast_normalized_jsonl,
        ]
    )

    run(
        [
            sys.executable,
            TOOLS / "select_replay_refine_cases.py",
            fast_normalized_jsonl,
            "--output",
            refine_cases,
            "--limit",
            str(args.refine_limit),
            "--max-per-source",
            str(args.refine_max_per_source),
        ]
    )

    run(
        [
            sys.executable,
            TOOLS / "rerun_refine_cases_chunked.py",
            refine_cases,
            "--player-name",
            args.player_name,
            "--lookahead-limit",
            str(args.refine_lookahead),
            "--snapshot-jsonl",
            refined_jsonl,
            "--summary-dir",
            refine_summary_dir,
            "--chunk-size",
            str(args.refine_chunk_size),
            "--append",
            "--skip-existing",
        ]
    )

    run(
        [
            sys.executable,
            TOOLS / "compare_fast_vs_refined.py",
            fast_normalized_jsonl,
            refined_jsonl,
            "--output",
            compare_json,
        ]
    )

    run(
        [
            sys.executable,
            TOOLS / "summarize_refine_changes.py",
            compare_json,
            "--output",
            change_summary,
        ]
    )

    run(
        [
            sys.executable,
            TOOLS / "analyze_refine_clusters.py",
            compare_json,
            "--output-json",
            cluster_json,
            "--output-md",
            cluster_md,
        ]
    )

    print("[pipeline] completed", dataset)
    print("[pipeline] compare", compare_json)
    print("[pipeline] summary", change_summary)
    print("[pipeline] cluster", cluster_md)


if __name__ == "__main__":
    main()
