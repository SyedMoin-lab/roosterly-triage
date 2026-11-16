"""Command-line entry point: ``python -m triage``."""

from __future__ import annotations

import argparse
import sys

from triage import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m triage",
        description="Triage Roosterly's open helpdesk tickets: reply, hand off or close.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
