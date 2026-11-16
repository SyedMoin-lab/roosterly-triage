import argparse
import asyncio
import json
import sys
import uuid
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import httpx
import openai
from pydantic import ValidationError
from pydantic_settings import BaseSettings

from triage import __version__
from triage.config import DatabaseSettings, HelpdeskSettings, ModelSettings
from triage.deciders import Decider, DrillDecider
from triage.evaluation.judge import Judge
from triage.evaluation.runner import compare_with, evaluate, summary, write_results
from triage.evaluation.scoring import score
from triage.helpdesk.client import HelpdeskClient
from triage.helpdesk.errors import AuthenticationError, HelpdeskError
from triage.helpdesk.models import HelpdeskStatus
from triage.journal.locks import RunnerAlreadyActiveError, runner_lock
from triage.journal.migrate import apply_migrations
from triage.journal.store import Journal, open_journal
from triage.knowledge.faq import Faq, load_faq
from triage.llm.gateway import ModelGateway
from triage.llm.roster import DRAFTING_MODELS, PRICES_AS_OF, TRIAGE_MODELS
from triage.pipeline.graph import Pipeline, PipelineDecider
from triage.pipeline.prompts import PROMPT_VERSIONS
from triage.retrieval import FaqIndex, GeminiEmbedder
from triage.runlog import RunLog
from triage.runner import ExitCode, FinalRunLockedError, Runner, RunOptions

DECIDER_NAMES = ("pipeline", "drill")


class ConfigurationError(Exception):
    pass


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return ExitCode.OK
    try:
        return int(asyncio.run(args.handler(args)))
    except ConfigurationError as error:
        print(error, file=sys.stderr)
        return ExitCode.USAGE
    except AuthenticationError as error:
        print(f"The helpdesk refused the key: {error}", file=sys.stderr)
        return ExitCode.USAGE
    except HelpdeskError as error:
        print(f"Helpdesk error: {error}", file=sys.stderr)
        return ExitCode.INCOMPLETE
    except (OSError, asyncpg.PostgresError) as error:
        print(
            f"Database error ({type(error).__name__}). Is it running? "
            "Start it with `docker compose up -d --wait db`.",
            file=sys.stderr,
        )
        return ExitCode.INCOMPLETE
    except KeyboardInterrupt:
        print("Interrupted. The next run settles anything that was in flight.", file=sys.stderr)
        return ExitCode.INTERRUPTED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m triage",
        description="Triage Roosterly's open helpdesk tickets: reply, hand off or close.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="command")

    status = commands.add_parser("status", help="show helpdesk and journal counts (read-only)")
    status.set_defaults(handler=status_command)

    run = commands.add_parser("run", help="decide and post one decision per open ticket")
    run.add_argument(
        "--decider",
        choices=DECIDER_NAMES,
        default="pipeline",
        help="pipeline: the AI agent (default); drill: hand off everything, no model calls",
    )
    run.add_argument("--dry-run", action="store_true", help="decide, but post nothing")
    run.add_argument("--limit", type=_positive_int, help="handle at most N tickets")
    run.add_argument("--concurrency", type=_positive_int, default=4, help="tickets at once")
    run.add_argument("--log-dir", type=Path, default=Path("logs"))
    run.set_defaults(handler=run_command)

    evaluation = commands.add_parser("eval", help="score the agent on the labelled examples")
    evaluation.add_argument("--repeats", type=_positive_int, default=3)
    evaluation.add_argument("--name", default="baseline", help="file name under eval/results")
    evaluation.add_argument("--compare-with", type=Path, help="an earlier results JSON file")
    evaluation.add_argument("--no-judge", action="store_true", help="skip the reply judge")
    evaluation.set_defaults(handler=eval_command)

    migrate = commands.add_parser("migrate", help="apply the database migrations")
    migrate.set_defaults(handler=migrate_command)

    reset = commands.add_parser("reset", help="re-open every practice ticket in the helpdesk")
    reset.add_argument("--yes", action="store_true", help="confirm the reset")
    reset.set_defaults(handler=reset_command)

    lock = commands.add_parser("lock", help="refuse live runs; use after the final run")
    lock.set_defaults(handler=lock_command)
    unlock = commands.add_parser("unlock", help="allow live runs again")
    unlock.set_defaults(handler=unlock_command)
    return parser


async def status_command(args: argparse.Namespace) -> int:
    async with HelpdeskClient.from_settings(load(HelpdeskSettings)) as helpdesk:
        print(format_status(await helpdesk.status()))
    database_url = _optional_database_url()
    if database_url is None:
        return ExitCode.OK
    try:
        async with open_journal(database_url, migrate=False) as journal:
            epoch = await journal.current_epoch()
            if epoch is None:
                print("journal: empty")
                return ExitCode.OK
            counts = ", ".join(
                f"{state}={n}" for state, n in sorted((await journal.counts(epoch)).items())
            )
            locked = await journal.final_run_locked()
    except (OSError, asyncpg.PostgresError) as error:
        print(f"journal: unavailable ({type(error).__name__})")
        return ExitCode.OK
    print(
        f"journal epoch {epoch}: {counts or 'no tickets'}{', final-run lock ON' if locked else ''}"
    )
    return ExitCode.OK


async def run_command(args: argparse.Namespace) -> int:
    helpdesk_settings = load(HelpdeskSettings)
    database_url = load(DatabaseSettings).database_url.get_secret_value()
    model_settings = load(ModelSettings) if args.decider == "pipeline" else None
    options = RunOptions(dry_run=args.dry_run, limit=args.limit, concurrency=args.concurrency)
    run_id = uuid.uuid4()
    try:
        async with (
            runner_lock(database_url),
            open_journal(database_url, max_connections=args.concurrency + 2) as journal,
            HelpdeskClient.from_settings(helpdesk_settings) as helpdesk,
        ):
            decider = await build_decider(model_settings, journal)
            with RunLog(args.log_dir, run_id) as log:
                runner = Runner(
                    helpdesk=helpdesk,
                    journal=journal,
                    decider=decider,
                    log=log,
                    run_id=run_id,
                    options=options,
                )
                summary = await runner.run()
                print(summary.describe())
                print(f"log: {log.path}")
                return summary.exit_code
    except RunnerAlreadyActiveError as error:
        print(error, file=sys.stderr)
        return ExitCode.ALREADY_RUNNING
    except FinalRunLockedError as error:
        print(error, file=sys.stderr)
        return ExitCode.LOCKED


async def build_decider(model_settings: ModelSettings | None, journal: Journal) -> Decider:
    if model_settings is None:
        return DrillDecider()
    faq = load_faq()
    retriever = await faq_index(journal, model_settings, faq)
    return PipelineDecider(Pipeline(ModelGateway(model_settings), faq, retriever), faq)


async def faq_index(journal: Journal, model_settings: ModelSettings, faq: Faq) -> FaqIndex | None:
    index = FaqIndex(journal.pool, GeminiEmbedder(model_settings), faq)
    try:
        await index.sync()
    except (openai.APIError, httpx.HTTPError, asyncpg.PostgresError) as error:
        print(
            f"FAQ retrieval is off ({type(error).__name__}); deciding without it.", file=sys.stderr
        )
        return None
    return index


async def eval_command(args: argparse.Namespace) -> int:
    helpdesk_settings, model_settings = load(HelpdeskSettings), load(ModelSettings)
    faq = load_faq()
    gateway = ModelGateway(model_settings)
    database_url = _optional_database_url()
    async with HelpdeskClient.from_settings(helpdesk_settings) as helpdesk:
        examples = await helpdesk.examples()
    async with AsyncExitStack() as stack:
        retriever = None
        if database_url is not None:
            journal = await stack.enter_async_context(open_journal(database_url))
            retriever = await faq_index(journal, model_settings, faq)
        attempts = await evaluate(
            PipelineDecider(Pipeline(gateway, faq, retriever), faq),
            examples,
            repeats=args.repeats,
            judge=None if args.no_judge else Judge(gateway, faq),
        )
    report = score(attempts)
    notes: dict[str, object] = {
        "run at": datetime.now(UTC).isoformat(timespec="seconds"),
        "repeats": args.repeats,
        "models": {spec.family: spec.model for spec in (*TRIAGE_MODELS, *DRAFTING_MODELS)},
        "prompt versions": PROMPT_VERSIONS,
        "faq": faq.sha256[:12],
        "prices as of": PRICES_AS_OF,
    }
    comparison = None
    if args.compare_with is not None:
        comparison = compare_with(args.compare_with, report)
        notes[f"compared with {args.compare_with.stem}"] = comparison
    path = Path("eval/results") / args.name
    write_results(path, report, title=f"Eval: {args.name}", notes=notes)
    print(json.dumps(summary(report), indent=2))
    if comparison is not None:
        print(comparison)
    print(f"results: {path.with_suffix('.md')}")
    return ExitCode.OK


async def migrate_command(args: argparse.Namespace) -> int:
    database_url = load(DatabaseSettings).database_url.get_secret_value()
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=1)
    try:
        applied = await apply_migrations(pool)
    finally:
        await pool.close()
    print(f"applied: {', '.join(applied)}" if applied else "database is up to date")
    return ExitCode.OK


async def reset_command(args: argparse.Namespace) -> int:
    if not args.yes:
        print(
            "This re-opens every practice ticket in the helpdesk. Run it again with --yes.",
            file=sys.stderr,
        )
        return ExitCode.USAGE
    helpdesk_settings = load(HelpdeskSettings)
    database_url = load(DatabaseSettings).database_url.get_secret_value()
    async with runner_lock(database_url), open_journal(database_url) as journal:
        if await journal.final_run_locked():
            print("The final run is locked: a reset would erase the scored run.", file=sys.stderr)
            return ExitCode.LOCKED
        async with HelpdeskClient.from_settings(helpdesk_settings) as helpdesk:
            await helpdesk.reset_practice()
        epoch = await journal.start_epoch("practice reset")
    print(f"Practice tickets re-opened. Journal epoch {epoch} started.")
    return ExitCode.OK


async def lock_command(args: argparse.Namespace) -> int:
    return await _set_lock(locked=True, reason="final run done")


async def unlock_command(args: argparse.Namespace) -> int:
    return await _set_lock(locked=False, reason="unlocked by hand")


async def _set_lock(*, locked: bool, reason: str) -> int:
    database_url = load(DatabaseSettings).database_url.get_secret_value()
    async with open_journal(database_url) as journal:
        await journal.set_final_run_lock(locked=locked, reason=reason)
    print("Final-run lock is ON: live runs are refused." if locked else "Final-run lock is OFF.")
    return ExitCode.OK


def load[SettingsT: BaseSettings](settings_type: type[SettingsT]) -> SettingsT:
    try:
        return settings_type()
    except ValidationError as error:
        raise ConfigurationError(describe_settings_error(error)) from error


def _optional_database_url() -> str | None:
    try:
        return load(DatabaseSettings).database_url.get_secret_value()
    except ConfigurationError:
        return None


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


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value
