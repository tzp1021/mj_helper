#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from urllib.parse import unquote
import xml.etree.ElementTree as ET


def classify_mjlog(path):
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "uuid": path.stem,
            "file": str(path),
            "valid": False,
            "reason": "xml_error",
            "detail": repr(exc),
        }

    un_elem = root.find("UN")
    init_elem = root.find("INIT")
    if un_elem is None:
        return {
            "uuid": path.stem,
            "file": str(path),
            "valid": False,
            "reason": "missing_un",
        }
    if init_elem is None:
        return {
            "uuid": path.stem,
            "file": str(path),
            "valid": False,
            "reason": "missing_init",
        }

    players = [unquote(un_elem.attrib.get(f"n{seat}", "")) for seat in range(4)]
    if any(not name for name in players):
        return {
            "uuid": path.stem,
            "file": str(path),
            "valid": False,
            "reason": "missing_player_name",
            "players": players,
        }

    action_count = 0
    for elem in root:
        tag = elem.tag
        if tag == "INIT" or tag == "N" or tag == "AGARI" or tag == "RYUUKYOKU":
            action_count += 1
        elif tag and len(tag) > 1 and tag[0] in "TUVWDEFG" and tag[1:].isdigit():
            action_count += 1

    seed = (init_elem.attrib.get("seed") or "").split(",")
    round_index = int(seed[0]) if seed and seed[0] else 0
    return {
        "uuid": path.stem,
        "file": str(path),
        "valid": True,
        "players": players,
        "action_count": action_count,
        "round_index": round_index,
        "dealer": int(init_elem.attrib.get("oya", 0)),
    }


def main():
    parser = argparse.ArgumentParser(description="Build validity manifest for Tenhou mjlog files.")
    parser.add_argument("--mjlog-dir", default="/Users/bigo/code/mj/data/tenhou/mjlog")
    parser.add_argument("--valid-output", default="/Users/bigo/code/mj/data/archive/valid_tenhou_mjlog_manifest.json")
    parser.add_argument("--invalid-output", default="/Users/bigo/code/mj/data/archive/invalid_tenhou_mjlog_manifest.json")
    args = parser.parse_args()

    root = Path(args.mjlog_dir)
    valid_rows = []
    invalid_rows = []

    for path in sorted(root.glob("*.mjlog")):
        row = classify_mjlog(path)
        if row["valid"]:
            valid_rows.append(row)
        else:
            invalid_rows.append(row)

    Path(args.valid_output).write_text(
        json.dumps({"count": len(valid_rows), "files": valid_rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    Path(args.invalid_output).write_text(
        json.dumps({"count": len(invalid_rows), "files": invalid_rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "valid_count": len(valid_rows),
                "invalid_count": len(invalid_rows),
                "valid_output": args.valid_output,
                "invalid_output": args.invalid_output,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
