#!/usr/bin/env python3
import argparse
import json
import shutil
from pathlib import Path


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def action_summary(action, index):
    if not isinstance(action, dict):
        return {"record_index": index, "name": None}
    summary = {
        "record_index": index,
        "name": action.get("name"),
        "type": action.get("type"),
        "passed": action.get("passed"),
        "raw_action": action,
    }
    for bucket_name in ["data", "user_event", "user_input"]:
        data = action.get(bucket_name)
        if not isinstance(data, dict):
            continue
        summary[bucket_name] = data
        for key in [
            "seat",
            "tile",
            "tiles",
            "type",
            "moqie",
            "is_liqi",
            "is_wliqi",
            "doras",
            "left_tile_count",
            "liqi",
            "operation",
            "operations",
        ]:
            if key in data:
                summary[key] = data[key]
    return summary


def event_summary(event, actions):
    record_index = event.get("record_index")
    linked_action = None
    if isinstance(record_index, int) and 0 <= record_index < len(actions):
        linked_action = action_summary(actions[record_index], record_index)
    return {
        "record_index": record_index,
        "seer_index": event.get("seer_index"),
        "event_type": event.get("type"),
        "actual_action": linked_action,
        "recommends": event.get("recommends"),
    }


def round_key_from_round(round_item):
    if not isinstance(round_item, dict):
        return None
    parts = [round_item.get("chang"), round_item.get("ju"), round_item.get("ben")]
    if any(part is None for part in parts):
        return None
    return f"{parts[0]}-{parts[1]}-{parts[2]}"


def round_key_from_action(action):
    if not isinstance(action, dict):
        return None
    if action.get("name") != "RecordNewRound":
        return None
    data = action.get("data") or {}
    parts = [data.get("chang"), data.get("ju"), data.get("ben")]
    if any(part is None for part in parts):
        return None
    return f"{parts[0]}-{parts[1]}-{parts[2]}"


def build_round_index(actions):
    round_starts = []
    for idx, action in enumerate(actions):
        key = round_key_from_action(action)
        if key is None:
            continue
        current = {
            "key": key,
            "start_record_index": idx,
            "end_record_index": len(actions) - 1,
        }
        if round_starts:
            round_starts[-1]["end_record_index"] = idx - 1
        round_starts.append(current)
    return round_starts


def find_round_for_record(round_ranges, record_index):
    if not isinstance(record_index, int):
        return None
    for item in round_ranges:
        if item["start_record_index"] <= record_index <= item["end_record_index"]:
            return item["key"]
    return None


def main():
    parser = argparse.ArgumentParser(description="Rebuild record_index-aligned paipu + Seer datasets.")
    parser.add_argument("--paipu-dir", default="/Users/bigo/code/mj/data/paipu_exports")
    parser.add_argument("--seer-dir", default="/Users/bigo/code/mj/data/seer_exports")
    parser.add_argument("--output-dir", default="/Users/bigo/code/mj/data/paipu_4p_aligned")
    args = parser.parse_args()

    paipu_dir = Path(args.paipu_dir)
    seer_dir = Path(args.seer_dir)
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    for child in outdir.iterdir():
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)

    paipu_files = {
        path.stem: path
        for path in paipu_dir.glob("*.json")
        if path.name not in {"manifest.json", "record_list_summary.json"}
    }
    seer_files = {path.name[:-10]: path for path in seer_dir.glob("*.seer.json")}

    outputs = []
    skipped = []
    for uuid in sorted(paipu_files.keys() & seer_files.keys()):
        paipu_path = paipu_files[uuid]
        seer_path = seer_files[uuid]
        paipu = load_json(paipu_path)
        seer = load_json(seer_path)

        accounts = paipu.get("accounts") or []
        actions = ((paipu.get("game_detail_records") or {}).get("actions") or [])
        report = ((seer.get("res") or {}).get("report") or {})
        events = report.get("events") or []
        rounds = report.get("rounds") or []

        if len(accounts) != 4 or not actions or not events:
            skipped.append({
                "uuid": uuid,
                "accounts": len(accounts),
                "action_count": len(actions),
                "seer_event_count": len(events),
                "reason": (
                    "not_4p" if len(accounts) != 4
                    else "missing_actions" if not actions
                    else "missing_seer_events"
                ),
            })
            continue

        round_ranges = build_round_index(actions)
        round_meta = {}
        for round_item in rounds:
            key = round_key_from_round(round_item)
            if key:
                round_meta[key] = round_item

        aligned_events = []
        for event in events:
            item = event_summary(event, actions)
            key = find_round_for_record(round_ranges, item["record_index"])
            item["round_key"] = key
            item["round"] = round_meta.get(key)
            aligned_events.append(item)

        payload = {
            "uuid": uuid,
            "status": "paired",
            "meta": {
                "action_count": len(actions),
                "seer_event_count": len(events),
                "seer_round_count": len(rounds),
            },
            "head": paipu.get("head"),
            "accounts": paipu.get("accounts"),
            "result": paipu.get("result"),
            "round_ranges": round_ranges,
            "round_alignment_note": "This export aligns Seer by record_index. Some paipu actions are compact user_event/user_input records rather than expanded RecordDiscardTile-style events, so raw_action is preserved.",
            "aligned_events": aligned_events,
        }
        target = outdir / f"{uuid}.aligned.json"
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        outputs.append({
            "uuid": uuid,
            "status": "paired",
            "file": str(target),
            "action_count": len(actions),
            "seer_event_count": len(events),
            "seer_round_count": len(rounds),
            "aligned_event_count": len(aligned_events),
        })

    manifest = {
        "count": len(outputs),
        "pairs": outputs,
        "skipped_count": len(skipped),
        "skipped": skipped,
    }
    (outdir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[aligned] files={len(outputs)} skipped={len(skipped)} -> {outdir}")


if __name__ == "__main__":
    main()
