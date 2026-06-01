#!/usr/bin/env python3
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Concatenate replay JSONL parts into one output file.")
    parser.add_argument("output")
    parser.add_argument("inputs", nargs="+")
    args = parser.parse_args()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("wb") as out_fh:
        for src in args.inputs:
            src_path = Path(src)
            if not src_path.exists():
                continue
            with src_path.open("rb") as in_fh:
                while True:
                    chunk = in_fh.read(1024 * 1024)
                    if not chunk:
                        break
                    out_fh.write(chunk)


if __name__ == "__main__":
    main()
