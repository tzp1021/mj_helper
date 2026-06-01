#!/usr/bin/env python3
import argparse
import gzip
import html
import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


LIST_URL = "https://tenhou.net/sc/raw/list.cgi"
RAW_BASE_URL = "https://tenhou.net/sc/raw/dat/"
LOG_BASE_URL = "http://tenhou.net/0/log/?"


def fetch_bytes(url, timeout):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "mj-local-research-downloader/0.1",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def parse_file_index(text):
    rows = []
    for file_name, size in re.findall(r"\{file:'([^']+)',size:(\d+)\}", text):
        rows.append({"file": file_name, "size": int(size)})
    return rows


def parse_log_ids(raw_html, include_east):
    text = gzip.decompress(raw_html).decode("utf-8", errors="replace")
    ids = []
    for line in text.splitlines():
        if "四鳳" not in line:
            continue
        if not include_east and "四鳳南" not in line:
            continue
        match = re.search(r"log=([^\" >]+)", html.unescape(line))
        if match:
            ids.append(match.group(1))
    return ids


def valid_mjlog(path):
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return False
    return root.tag == "mjloggm" and root.find("GO") is not None


def count_valid_mjlogs(mjlog_dir):
    return sum(1 for path in mjlog_dir.glob("*.mjlog") if valid_mjlog(path))


def is_valid_in_dirs(log_id, dirs):
    name = f"{log_id}.mjlog"
    for dir_path in dirs:
        path = dir_path / name
        if path.exists() and valid_mjlog(path):
            return True
    return False


def main():
    parser = argparse.ArgumentParser(description="Conservative Tenhou mjlog downloader.")
    parser.add_argument("--target-count", type=int, default=500)
    parser.add_argument("--mjlog-dir", default="/Users/bigo/code/mj/data/tenhou/mjlog")
    parser.add_argument("--raw-dir", default="/Users/bigo/code/mj/data/tenhou/raw_lists")
    parser.add_argument("--state-file", default="/Users/bigo/code/mj/data/tenhou/download_state.json")
    parser.add_argument("--delay-seconds", type=float, default=1.5)
    parser.add_argument("--raw-delay-seconds", type=float, default=1.0)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument(
        "--exclude-dir",
        action="append",
        default=[],
        help="Directory containing existing mjlogs to skip. Can be passed multiple times.",
    )
    parser.add_argument("--include-east", action="store_true", help="Include four-player east games too.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    mjlog_dir = Path(args.mjlog_dir)
    raw_dir = Path(args.raw_dir)
    state_path = Path(args.state_file)
    exclude_dirs = [Path(item) for item in args.exclude_dir]
    mjlog_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    state = {}
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    raw_sizes = state.setdefault("raw_sizes", {})

    index_text = fetch_bytes(LIST_URL, args.timeout_seconds).decode("utf-8", errors="replace")
    index_rows = [row for row in parse_file_index(index_text) if row["file"].startswith("scc")]
    index_rows.sort(key=lambda row: row["file"], reverse=True)

    valid_count = count_valid_mjlogs(mjlog_dir)
    print(f"[tenhou] existing_valid={valid_count} target={args.target_count}", flush=True)
    downloaded = 0
    skipped_existing = 0
    skipped_excluded = 0
    failed = []

    for row in index_rows:
        if valid_count >= args.target_count:
            break

        file_name = row["file"]
        raw_path = raw_dir / file_name
        raw_html = None
        old_size = raw_sizes.get(file_name)
        if raw_path.exists() and old_size == row["size"]:
            raw_html = raw_path.read_bytes()
        else:
            url = RAW_BASE_URL + file_name
            if args.dry_run:
                print(f"[tenhou] would fetch raw {file_name}", flush=True)
                continue
            try:
                raw_html = fetch_bytes(url, args.timeout_seconds)
                raw_path.write_bytes(raw_html)
                raw_sizes[file_name] = row["size"]
                state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                print(f"[tenhou] raw {file_name} bytes={len(raw_html)}", flush=True)
                time.sleep(args.raw_delay_seconds)
            except Exception as exc:
                failed.append({"file": file_name, "error": repr(exc)})
                print(f"[tenhou] raw failed {file_name}: {exc}", flush=True)
                continue

        try:
            log_ids = parse_log_ids(raw_html, args.include_east)
        except Exception as exc:
            failed.append({"file": file_name, "error": repr(exc)})
            print(f"[tenhou] parse failed {file_name}: {exc}", flush=True)
            continue

        for log_id in log_ids:
            if valid_count >= args.target_count:
                break
            target = mjlog_dir / f"{log_id}.mjlog"
            if target.exists() and valid_mjlog(target):
                skipped_existing += 1
                continue
            if is_valid_in_dirs(log_id, exclude_dirs):
                skipped_excluded += 1
                continue
            if args.dry_run:
                print(f"[tenhou] would fetch {log_id}", flush=True)
                valid_count += 1
                continue
            try:
                body = fetch_bytes(LOG_BASE_URL + log_id, args.timeout_seconds)
                target.write_bytes(body)
                if valid_mjlog(target):
                    valid_count += 1
                    downloaded += 1
                    print(f"[tenhou] fetched {log_id} valid={valid_count}/{args.target_count}", flush=True)
                else:
                    failed.append({"log_id": log_id, "error": "invalid_mjlog"})
                    print(f"[tenhou] invalid {log_id}", flush=True)
                time.sleep(args.delay_seconds)
            except Exception as exc:
                failed.append({"log_id": log_id, "error": repr(exc)})
                print(f"[tenhou] failed {log_id}: {exc}", flush=True)
                time.sleep(max(args.delay_seconds, 5.0))

    state["last_run"] = {
        "target_count": args.target_count,
        "valid_count": valid_count,
        "downloaded": downloaded,
        "skipped_existing": skipped_existing,
        "skipped_excluded": skipped_excluded,
        "failed": failed[-20:],
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "valid_count": valid_count,
                "downloaded": downloaded,
                "skipped_existing": skipped_existing,
                "skipped_excluded": skipped_excluded,
                "failed_count": len(failed),
                "state_file": str(state_path),
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
