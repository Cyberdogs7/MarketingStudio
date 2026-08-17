"""Marketing Studio entry point.

    python studio.py [--port 8126]

Starts the dashboard (all UX). Ported from the anime studio launcher.
"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="marketing-studio")
    ap.add_argument("--port", type=int, default=8126, help="dashboard port")
    ap.add_argument("--bind", default="127.0.0.1", help="dashboard bind address")
    args = ap.parse_args(argv)

    import logging
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from studio.dashboard import serve
    serve(port=args.port, bind=args.bind)
    return 0


if __name__ == "__main__":
    sys.exit(main())
