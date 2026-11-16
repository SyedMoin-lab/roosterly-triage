import argparse
import asyncio
import sys
from enum import IntEnum

from pydantic import ValidationError

from triage import __version__
from triage.config import HelpdeskSettings
from triage.helpdesk.client import HelpdeskClient
from triage.helpdesk.errors import HelpdeskError
from triage.helpdesk.models import HelpdeskStatus


class ExitCode(IntEnum):
    OK = 0
    FAILED = 1
    USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m triage",
        description="Triage Roosterly's open helpdesk tickets: reply, hand off or close.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="command")
    commands.add_parser("status", help="show the helpdesk's mode and ticket counts (read-only)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return ExitCode.OK
    try:
        settings = HelpdeskSettings()
    except ValidationError as error:
        print(describe_settings_error(error), file=sys.stderr)
        return ExitCode.USAGE
    try:
        print(asyncio.run(fetch_status(settings)))
    except HelpdeskError as error:
        print(f"Helpdesk error: {error}", file=sys.stderr)
        return ExitCode.FAILED
    return ExitCode.OK


async def fetch_status(settings: HelpdeskSettings) -> str:
    async with HelpdeskClient.from_settings(settings) as client:
        return format_status(await client.status())


def format_status(status: HelpdeskStatus) -> str:
    return (
        f"mode={status.mode} candidate={status.candidate} "
        f"open={status.open_tickets} handled={status.handled_tickets}"
    )


def describe_settings_error(error: ValidationError) -> str:
    lines = ["Configuration error. Copy .env.example to .env and fill it in:"]
    for problem in error.errors():
        name = "_".join(str(part) for part in problem["loc"]).upper()
        lines.append(f"  {name}: {problem['msg']}")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
