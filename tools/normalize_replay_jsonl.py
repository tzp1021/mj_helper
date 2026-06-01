#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def iter_json_objects_from_line(line: str):
    decoder = json.JSONDecoder()
    idx = 0
    length = len(line)
    while idx < length:
        while idx < length and line[idx].isspace():
            idx += 1
        if idx >= length:
            break
        obj, end = decoder.raw_decode(line, idx)
        yield obj
        idx = end


def main():
    parser = argparse.ArgumentParser(
        description="Normalize replay JSONL by splitting accidentally concatenated JSON objects."
    )
    parser.add_argument("input_jsonl")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    in_path = Path(args.input_jsonl)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    expanded_lines = 0
    bad_lines = 0
    with in_path.open(encoding="utf-8") as in_fh, out_path.open("w", encoding="utf-8") as out_fh:
        for line_no, raw_line in enumerate(in_fh, 1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                objs = list(iter_json_objects_from_line(line))
            except Exception as exc:
                bad_lines += 1
                print(
                    json.dumps(
                        {
                            "line": line_no,
                            "error": repr(exc),
                        },
                        ensure_ascii=False,
                    )
                )
                continue
            if len(objs) > 1:
                expanded_lines += 1
            for obj in objs:
                out_fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
                total += 1

    print(
        json.dumps(
            {
                "input": str(in_path),
                "output": str(out_path),
                "rows": total,
                "expanded_lines": expanded_lines,
                "bad_lines": bad_lines,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
