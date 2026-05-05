#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import shutil
from pathlib import Path


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Build a date-range folder of 4p paipu with current Seer availability status.")
    parser.add_argument("--summary-json", default="/Users/bigo/code/mj/paipu_exports/record_list_summary.json")
    parser.add_argument("--paipu-dir", default="/Users/bigo/code/mj/paipu_exports")
    parser.add_argument("--seer-dir", default="/Users/bigo/code/mj/seer_exports")
    parser.add_argument("--output-dir", default="/Users/bigo/code/mj/tmp_paipu_4p_20250502_0531_status")
    parser.add_argument("--start", default="2025-05-02 17:50")
    parser.add_argument("--end", default="2025-05-31 17:59")
    args = parser.parse_args()

    start_ts = int(dt.datetime.strptime(args.start, "%Y-%m-%d %H:%M").timestamp())
    end_ts = int(dt.datetime.strptime(args.end, "%Y-%m-%d %H:%M").timestamp())

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    for child in outdir.iterdir():
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)

    summary = load_json(args.summary_json)
    seer_dir = Path(args.seer_dir)
    seer_uuids = {path.name[:-10]: path for path in seer_dir.glob("*.seer.json")}
    paipu_dir = Path(args.paipu_dir)

    picked = {}
    for row in summary:
        uuid = row.get("uuid")
        ts = row.get("end_time") or row.get("start_time") or 0
        if not uuid or len(row.get("players") or []) != 4:
            continue
        if not (start_ts <= ts <= end_ts):
            continue
        prev = picked.get(uuid)
        if prev is None or ts > (prev.get("end_time") or prev.get("start_time") or 0):
            picked[uuid] = row

    manifest_rows = []
    for uuid, row in sorted(picked.items(), key=lambda kv: kv[1].get("end_time") or kv[1].get("start_time") or 0, reverse=True):
        paipu_path = paipu_dir / f"{uuid}.json"
        seer_path = seer_uuids.get(uuid)
        copied_paipu = None
        copied_seer = None
        action_count = 0
        if paipu_path.exists():
            shutil.copy2(paipu_path, outdir / paipu_path.name)
            copied_paipu = str(outdir / paipu_path.name)
            try:
                paipu = load_json(paipu_path)
                action_count = len(((paipu.get("game_detail_records") or {}).get("actions") or []))
            except Exception:
                action_count = 0
        seer_event_count = 0
        if seer_path and seer_path.exists():
            shutil.copy2(seer_path, outdir / seer_path.name)
            copied_seer = str(outdir / seer_path.name)
            try:
                seer = load_json(seer_path)
                seer_event_count = len((((seer.get("res") or {}).get("report") or {}).get("events") or []))
            except Exception:
                seer_event_count = 0
        manifest_rows.append({
            "uuid": uuid,
            "end_time": row.get("end_time"),
            "subtag": row.get("subtag"),
            "standard_rule": row.get("standard_rule"),
            "status": "paired" if copied_seer else "missing_seer",
            "paipu_file": copied_paipu,
            "seer_file": copied_seer,
            "action_count": action_count,
            "seer_event_count": seer_event_count,
        })

    (outdir / "manifest.json").write_text(
        json.dumps({
            "start": args.start,
            "end": args.end,
            "count": len(manifest_rows),
            "rows": manifest_rows,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[range] files={len(manifest_rows)} -> {outdir}")


if __name__ == "__main__":
    main()
