#!/usr/bin/env python3
"""Serve the local asset previewer."""

from __future__ import annotations

import argparse
import http.server
import socketserver
from pathlib import Path


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()

    root = args.root.resolve()
    handler = lambda *handler_args, **handler_kwargs: QuietHandler(  # noqa: E731
        *handler_args,
        directory=str(root),
        **handler_kwargs,
    )
    with socketserver.TCPServer((args.host, args.port), handler) as server:
        print(f"Serving {root}")
        print(f"Open http://{args.host}:{args.port}/asset_preview/")
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
