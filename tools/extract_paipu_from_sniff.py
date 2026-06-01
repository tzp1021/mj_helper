#!/usr/bin/env python3
import argparse
import base64
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import parse_majsoul_har as pmh


def load_jsonl(path):
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def write_json(path, payload):
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def summarize_entries(rows):
    entries = []
    for row in rows:
        if row.get("kind") != "response":
            continue
        method = row.get("method", "")
        decoded = row.get("decoded") or {}
        if method.endswith("fetchNextGameRecordList") or method.endswith("fetchGameRecordListV2") or method.endswith("fetchGameRecordList"):
            for entry in decoded.get("entries") or []:
                players = []
                for p in entry.get("players") or []:
                    players.append({
                        "seat": p.get("seat"),
                        "rank": p.get("rank"),
                        "nickname": p.get("nickname"),
                        "account_id": p.get("account_id"),
                        "point": p.get("point"),
                    })
                entries.append({
                    "uuid": entry.get("uuid"),
                    "start_time": entry.get("start_time"),
                    "end_time": entry.get("end_time"),
                    "tag": entry.get("tag"),
                    "subtag": entry.get("subtag"),
                    "standard_rule": entry.get("standard_rule"),
                    "players": players,
                })
    return entries


def extract_fetch_game_records(rows, output_dir):
    schema = pmh.LiqiSchema(json.loads(Path("/Users/bigo/code/mj/liqi.json").read_text(encoding="utf-8")))
    exported = []
    for row in rows:
        if row.get("kind") != "response":
            continue
        if not str(row.get("method", "")).endswith("fetchGameRecord"):
            continue
        decoded = row.get("decoded") or {}
        head = decoded.get("head") or {}
        uuid = (head.get("uuid") or f"rpc-{row.get('rpc_id')}").strip()
        out = {
            "meta": {
                "rpc_id": row.get("rpc_id"),
                "method": row.get("method"),
                "ts": row.get("ts"),
            },
            "head": head,
            # fetchGameRecord responses often carry accounts/result under head.
            "result": decoded.get("result", head.get("result")),
            "accounts": decoded.get("accounts", head.get("accounts")),
        }

        data = decoded.get("data")
        raw_base64 = None
        if isinstance(data, dict) and data.get("_base64"):
            raw_base64 = data["_base64"]
        elif isinstance(data, str) and data:
            raw_base64 = data

        if raw_base64:
            raw = base64.b64decode(raw_base64)
            try:
                fields = pmh.parse_simple_protobuf(raw)
                wrapped_name = None
                wrapped_body = None
                for field_id, wire_type, value in fields:
                    if field_id == 1 and wire_type == 2:
                        wrapped_name = value.decode("utf-8", errors="replace")
                    elif field_id == 2 and wire_type == 2:
                        wrapped_body = value
                out["game_detail_records_wrapper"] = {
                    "name": wrapped_name,
                    "body_len": len(wrapped_body or b""),
                }
                if wrapped_name == ".lq.GameDetailRecords" and wrapped_body:
                    out["game_detail_records"] = schema.decode_message(wrapped_body, "GameDetailRecords")
                else:
                    out["game_detail_records_decode_error"] = f"unexpected wrapper name: {wrapped_name!r}"
                    out["game_detail_records_raw_base64"] = raw_base64
            except Exception as exc:
                out["game_detail_records_decode_error"] = repr(exc)
                out["game_detail_records_raw_base64"] = raw_base64

        target = Path(output_dir) / f"{uuid}.json"
        write_json(target, out)
        exported.append(str(target))
    return exported


def main():
    parser = argparse.ArgumentParser(description="Extract Majsoul paipu data from paipu_sniff.jsonl")
    parser.add_argument("--input", default="/Users/bigo/code/mj/data/paipu_sniff.jsonl")
    parser.add_argument("--output-dir", default="/Users/bigo/code/mj/data/paipu_exports")
    args = parser.parse_args()

    rows = load_jsonl(args.input)
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    entries = summarize_entries(rows)
    write_json(outdir / "record_list_summary.json", entries)
    exported = extract_fetch_game_records(rows, outdir)

    print(f"[extract] summaries: {outdir / 'record_list_summary.json'}")
    print(f"[extract] game records: {len(exported)}")
    for path in exported:
        print(path)


if __name__ == "__main__":
    main()
