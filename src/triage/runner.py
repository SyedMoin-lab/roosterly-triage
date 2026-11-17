import asyncio
import logging
import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import IntEnum
from uuid import UUID

from triage.deciders import Decider, ProviderOutageError
from triage.domain import Decision, Ticket
from triage.helpdesk.client import HelpdeskClient
from triage.helpdesk.errors import (
    AlreadyHandledError,
    AuthenticationError,
    HelpdeskError,
    HelpdeskUnavailableError,
    NotFoundError,
    RequestRejectedError,
    ValidationFailedError,
    WriteOutcomeUnknownError,
)
from triage.journal.states import FINISHED, Outcome, TicketState
from triage.journal.store import Journal
from triage.progress import ticket_scope
from triage.runlog import RunLog

type CrashHook = Callable[[str, str], None]

_SHOWN_OUTCOMES = {
    Outcome.POSTED: "posted",
    Outcome.PREVIEWED: "decided, not posted (dry run)",
    Outcome.DEFERRED: "left open for the next run",
    Outcome.DECIDE_FAILED: "left open, the decision failed",
    Outcome.ALREADY_HANDLED: "already answered (409), not sent again",
    Outcome.CONFIRMED_BY_READ: "posted, confirmed by reading it back",
    Outcome.HANDLED_ELSEWHERE: "handled outside this run",
    Outcome.UNSETTLED: "not settled yet, the next run checks it",
    Outcome.REJECTED: "rejected by the helpdesk",
    Outcome.NOT_IN_SET: "not in this ticket set",
}

log = logging.getLogger(__name__)


class ExitCode(IntEnum):
    OK = 0
    INCOMPLETE = 1
    USAGE = 2
    PROVIDER_DOWN = 3
    LOCKED = 4
    ALREADY_RUNNING = 5
    INTERRUPTED = 130


class FinalRunLockedError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class RunOptions:
    dry_run: bool = False
    limit: int | None = None
    concurrency: int = 4
    max_post_attempts: int = 3


@dataclass
class RunSummary:
    epoch: int
    outcomes: Counter[Outcome] = field(default_factory=Counter)
    provider_outage: bool = False

    @property
    def exit_code(self) -> ExitCode:
        if self.provider_outage:
            return ExitCode.PROVIDER_DOWN
        if any(count for outcome, count in self.outcomes.items() if outcome not in FINISHED):
            return ExitCode.INCOMPLETE
        return ExitCode.OK

    def describe(self) -> str:
        counts = ", ".join(f"{outcome}={count}" for outcome, count in sorted(self.outcomes.items()))
        return f"epoch {self.epoch}: {counts or 'no open tickets'} (exit {self.exit_code.value})"


@dataclass(frozen=True, slots=True)
class _Result:
    outcome: Outcome
    decision: Decision | None = None
    detail: str | None = None
    trace: Mapping[str, object] = field(default_factory=dict)


def _never_crash(point: str, ticket_id: str) -> None:
    return None


class Runner:
    def __init__(
        self,
        *,
        helpdesk: HelpdeskClient,
        journal: Journal,
        decider: Decider,
        log: RunLog,
        run_id: UUID,
        options: RunOptions | None = None,
        crash_hook: CrashHook | None = None,
    ) -> None:
        self._helpdesk = helpdesk
        self._journal = journal
        self._decider = decider
        self._log = log
        self._run_id = run_id
        self._options = options or RunOptions()
        self._crash = crash_hook or _never_crash

    async def run(self) -> RunSummary:
        dry_run = self._options.dry_run
        if not dry_run and await self._journal.final_run_locked():
            raise FinalRunLockedError(
                "The final run is locked. Live runs are refused until `python -m triage unlock`."
            )
        epoch = await self._journal.current_epoch() or await self._journal.start_epoch("first run")
        summary = RunSummary(epoch)
        if not dry_run:
            await self._journal.release_claims(epoch)
            await self._reconcile_posting(epoch, summary)
        open_tickets = sorted(
            await self._helpdesk.open_tickets(), key=lambda ticket: (ticket.received_at, ticket.id)
        )
        if not dry_run:
            epoch = await self._epoch_for(epoch, open_tickets)
            summary.epoch = epoch
        await self._journal.start_run(
            self._run_id,
            epoch,
            mode="dry_run" if dry_run else "live",
            decider=self._decider.name,
            concurrency=self._options.concurrency,
        )
        work = await self._plan(epoch, open_tickets, summary)
        log.info(
            "%d open tickets to handle, %d at a time%s",
            len(work),
            self._options.concurrency,
            "; dry run, nothing is posted" if dry_run else "",
        )
        semaphore = asyncio.Semaphore(self._options.concurrency)
        try:
            async with asyncio.TaskGroup() as group:
                for ticket, state in work:
                    group.create_task(self._handle(epoch, ticket, state, semaphore, summary))
        except BaseExceptionGroup as failures:
            raise _first_leaf(failures) from None
        await self._journal.finish_run(
            self._run_id,
            exit_code=summary.exit_code,
            summary={outcome.value: count for outcome, count in summary.outcomes.items()},
        )
        return summary

    async def _epoch_for(self, epoch: int, open_tickets: list[Ticket]) -> int:
        states = await self._journal.states(epoch)
        if any(states.get(ticket.id) is TicketState.DONE for ticket in open_tickets):
            return await self._journal.start_epoch("helpdesk reset detected")
        return epoch

    async def _plan(
        self, epoch: int, open_tickets: list[Ticket], summary: RunSummary
    ) -> list[tuple[Ticket, TicketState]]:
        if self._options.dry_run:
            work = [(ticket, TicketState.NEW) for ticket in open_tickets]
        else:
            open_ids = [ticket.id for ticket in open_tickets]
            await self._journal.add_tickets(epoch, open_tickets)
            await self._journal.reopen_failed(epoch, open_ids)
            for ticket_id in await self._journal.close_missing(epoch, open_ids):
                self._record(summary, epoch, ticket_id, _Result(Outcome.HANDLED_ELSEWHERE), 0.0)
            states = await self._journal.states(epoch)
            work = [
                (ticket, states[ticket.id])
                for ticket in open_tickets
                if states.get(ticket.id) in (TicketState.NEW, TicketState.DECIDED)
            ]
        limit = self._options.limit
        return work if limit is None else work[:limit]

    async def _reconcile_posting(self, epoch: int, summary: RunSummary) -> None:
        for ticket_id in await self._journal.ids_in_state(epoch, TicketState.POSTING):
            outcome = await self._settle_by_reading(epoch, ticket_id)
            if outcome is not None:
                self._record(summary, epoch, ticket_id, _Result(outcome), 0.0)

    async def _handle(
        self,
        epoch: int,
        ticket: Ticket,
        state: TicketState,
        semaphore: asyncio.Semaphore,
        summary: RunSummary,
    ) -> None:
        async with semaphore:
            with ticket_scope(ticket.id):
                log.info(
                    "started: %s ticket, %s plan",
                    ticket.channel or "unknown",
                    ticket.customer_plan or "unknown",
                )
                started = time.perf_counter()
                result = await self._decide_and_deliver(epoch, ticket, state, summary)
                if result is not None:
                    self._record(summary, epoch, ticket.id, result, time.perf_counter() - started)

    async def _decide_and_deliver(
        self, epoch: int, ticket: Ticket, state: TicketState, summary: RunSummary
    ) -> _Result | None:
        if state is TicketState.DECIDED:
            decision = await self._journal.frozen_decision(epoch, ticket.id)
            return _Result(await self._deliver(epoch, ticket.id, decision), decision)
        dry_run = self._options.dry_run
        if not dry_run and not await self._journal.claim(epoch, ticket.id, self._run_id):
            return None
        self._crash("after_claim", ticket.id)
        try:
            verdict = await self._decider.decide(ticket)
        except ProviderOutageError as error:
            summary.provider_outage = True
            await self._release(epoch, ticket.id)
            return _Result(Outcome.DEFERRED, detail=str(error))
        except Exception as error:
            await self._release(epoch, ticket.id)
            return _Result(Outcome.DECIDE_FAILED, detail=f"{type(error).__name__}: {error}")
        if dry_run:
            return _Result(Outcome.PREVIEWED, verdict.decision, trace=verdict.trace)
        await self._journal.record_decision(
            epoch, ticket.id, self._run_id, verdict.decision, verdict.trace
        )
        self._crash("after_decision", ticket.id)
        outcome = await self._deliver(epoch, ticket.id, verdict.decision)
        return _Result(outcome, verdict.decision, trace=verdict.trace)

    async def _deliver(self, epoch: int, ticket_id: str, decision: Decision) -> Outcome:
        for _ in range(self._options.max_post_attempts):
            if not await self._journal.begin_posting(epoch, ticket_id):
                return Outcome.UNSETTLED
            self._crash("after_posting_claim", ticket_id)
            try:
                await self._helpdesk.submit(ticket_id, decision)
            except AlreadyHandledError:
                return await self._finish(epoch, ticket_id, Outcome.ALREADY_HANDLED)
            except WriteOutcomeUnknownError:
                settled = await self._settle_by_reading(epoch, ticket_id)
                if settled is not None:
                    return settled
                continue
            except HelpdeskUnavailableError:
                await self._back_to_decided(epoch, ticket_id)
                return Outcome.DEFERRED
            except NotFoundError:
                return await self._fail(epoch, ticket_id, Outcome.NOT_IN_SET)
            except (ValidationFailedError, RequestRejectedError):
                return await self._fail(epoch, ticket_id, Outcome.REJECTED)
            except AuthenticationError:
                await self._back_to_decided(epoch, ticket_id)
                raise
            self._crash("after_post", ticket_id)
            return await self._finish(epoch, ticket_id, Outcome.POSTED)
        return Outcome.DEFERRED

    async def _settle_by_reading(self, epoch: int, ticket_id: str) -> Outcome | None:
        try:
            detail = await self._helpdesk.ticket(ticket_id)
        except NotFoundError:
            return await self._fail(epoch, ticket_id, Outcome.NOT_IN_SET)
        except AuthenticationError:
            raise
        except HelpdeskError:
            return Outcome.UNSETTLED
        if detail.is_handled:
            return await self._finish(epoch, ticket_id, Outcome.CONFIRMED_BY_READ)
        await self._back_to_decided(epoch, ticket_id)
        return None

    async def _finish(self, epoch: int, ticket_id: str, outcome: Outcome) -> Outcome:
        await self._journal.move(
            epoch, ticket_id, expected=TicketState.POSTING, to=TicketState.DONE, outcome=outcome
        )
        return outcome

    async def _fail(self, epoch: int, ticket_id: str, outcome: Outcome) -> Outcome:
        await self._journal.move(
            epoch, ticket_id, expected=TicketState.POSTING, to=TicketState.FAILED, outcome=outcome
        )
        return outcome

    async def _back_to_decided(self, epoch: int, ticket_id: str) -> None:
        await self._journal.move(
            epoch, ticket_id, expected=TicketState.POSTING, to=TicketState.DECIDED
        )

    async def _release(self, epoch: int, ticket_id: str) -> None:
        if not self._options.dry_run:
            await self._journal.move(
                epoch, ticket_id, expected=TicketState.DECIDING, to=TicketState.NEW
            )

    def _record(
        self, summary: RunSummary, epoch: int, ticket_id: str, result: _Result, seconds: float
    ) -> None:
        summary.outcomes[result.outcome] += 1
        decision = result.decision
        self._log.write(
            ticket_id,
            epoch=epoch,
            mode="dry_run" if self._options.dry_run else "live",
            decider=self._decider.name,
            outcome=result.outcome.value,
            action=None if decision is None else decision.action.value,
            category=None if decision is None else decision.category.value,
            priority=None if decision is None else decision.priority.value,
            confidence=None if decision is None else decision.confidence,
            reason=None if decision is None else decision.reason,
            codes=result.trace.get("codes", []),
            tokens=result.trace.get("tokens"),
            cost_usd=result.trace.get("cost_usd"),
            detail=result.detail,
            duration_ms=round(seconds * 1000),
        )
        log.info("%s", _describe_result(result, seconds), extra={"ticket": ticket_id})


def _describe_result(result: _Result, seconds: float) -> str:
    text = _SHOWN_OUTCOMES.get(result.outcome, str(result.outcome))
    decision = result.decision
    if decision is not None:
        text += f": {decision.action}, {decision.category}, {decision.priority}"
    elif result.detail:
        text += f": {result.detail.split(':', 1)[0]}"
    return f"{text} ({seconds:.0f} s)" if seconds else text


def _first_leaf(group: BaseExceptionGroup[BaseException]) -> BaseException:
    leaf: BaseException = group
    while isinstance(leaf, BaseExceptionGroup):
        leaf = leaf.exceptions[0]
    return leaf
