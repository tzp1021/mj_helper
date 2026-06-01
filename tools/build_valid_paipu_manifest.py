#!/usr/bin/env python3
import argparse
import json
from collections import Counter
from pathlib import Path


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def classify_paipu(path):
    try:
        payload = load_json(path)
    except Exception as exc:
        return {
            "uuid": path.stem,
            "file": str(path),
            "valid": False,
            "reason": "json_error",
            "detail": repr(exc),
        }

    accounts = payload.get("accounts")
    actions = ((payload.get("game_detail_records") or {}).get("actions") or [])
    decode_error = payload.get("game_detail_records_decode_error")
    head = payload.get("head") or {}
    mode_id = (((head.get("config") or {}).get("meta") or {}).get("mode_id"))

    if decode_error == "missing data payload":
        return {
            "uuid": path.stem,
            "file": str(path),
            "valid": False,
            "reason": "missing_data_payload",
            "mode_id": mode_id,
        }
    if not isinstance(accounts, list):
        return {
            "uuid": path.stem,
            "file": str(path),
            "valid": False,
            "reason": "missing_accounts",
            "mode_id": mode_id,
        }
    if len(accounts) != 4:
        return {
            "uuid": path.stem,
            "file": str(path),
            "valid": False,
            "reason": "not_4p",
            "player_count": len(accounts),
            "mode_id": mode_id,
        }
    if not actions:
        return {
            "uuid": path.stem,
            "file": str(path),
            "valid": False,
            "reason": "empty_actions",
            "mode_id": mode_id,
        }

    return {
        "uuid": path.stem,
        "file": str(path),
        "valid": True,
        "action_count": len(actions),
        "mode_id": mode_id,
        "start_time": head.get("start_time"),
        "end_time": head.get("end_time"),
    }


def main():
    parser = argparse.ArgumentParser(description="Build validity manifests for paipu exports.")
    parser.add_argument("--paipu-dir", default="/Users/bigo/code/mj/data/paipu_exports")
    parser.add_argument("--valid-output", default="/Users/bigo/code/mj/data/archive/valid_paipu_manifest.json")
    parser.add_argument("--invalid-output", default="/Users/bigo/code/mj/data/archive/invalid_paipu_manifest.json")
    args = parser.parse_args()

    paipu_dir = Path(args.paipu_dir)
    valid_rows = []
    invalid_rows = []
    reason_counter = Counter()

    for path in sorted(paipu_dir.glob("*.json")):
        if (
            path.name in {"manifest.json", "record_list_summary.json"}
            or path.name.startswith("manifest_")
        ):
            continue
        row = classify_paipu(path)
        if row["valid"]:
            valid_rows.append(row)
        else:
            invalid_rows.append(row)
            reason_counter[row["reason"]] += 1

    valid_payload = {
        "count": len(valid_rows),
        "files": valid_rows,
    }
    invalid_payload = {
        "count": len(invalid_rows),
        "reason_counts": dict(reason_counter.most_common()),
        "files": invalid_rows,
    }

    Path(args.valid_output).write_text(
        json.dumps(valid_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    Path(args.invalid_output).write_text(
        json.dumps(invalid_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "valid_count": len(valid_rows),
                "invalid_count": len(invalid_rows),
                "reason_counts": dict(reason_counter.most_common()),
                "valid_output": str(args.valid_output),
                "invalid_output": str(args.invalid_output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
