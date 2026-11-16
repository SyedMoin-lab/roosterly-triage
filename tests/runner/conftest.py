import json
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tests.fakes.clock import FakeClock
from tests.fakes.helpdesk import Connect, FakeHelpdesk, make_ticket
from triage.deciders import DrillDecider, ProviderOutageError, Verdict
from triage.domain import Ticket
from triage.journal.store import Journal
from triage.runlog import RunLog
from triage.runner import CrashHook, Runner, RunOptions, RunSummary

TICKETS = 30


class SimulatedCrash(BaseException):
    pass


def crash_at(point: str, ticket_id: str) -> CrashHook:
    def hook(seen_point: str, seen_ticket: str) -> None:
        if (seen_point, seen_ticket) == (point, ticket_id):
            raise SimulatedCrash(f"{point} on {ticket_id}")

    return hook


@dataclass
class ScriptedDecider:
    name: str = "scripted"
    calls: Counter[str] = field(default_factory=Counter)
    failing: frozenset[str] = frozenset()
    outage: bool = False
    before_decide: Callable[[Ticket], None] | None = None

    async def decide(self, ticket: Ticket) -> Verdict:
        self.calls[ticket.id] += 1
        if self.outage:
            raise ProviderOutageError("every model for triage is down")
        if ticket.id in self.failing:
            raise ValueError(f"decider bug on {ticket.id}")
        if self.before_decide is not None:
            self.before_decide(ticket)
        return await DrillDecider().decide(ticket)


@dataclass
class Harness:
    connect: Connect
    fake: FakeHelpdesk
    journal: Journal
    log_dir: Path
    decider: ScriptedDecider

    async def run(
        self, options: RunOptions | None = None, crash_hook: CrashHook | None = None
    ) -> RunSummary:
        run_id = uuid.uuid4()
        async with self.connect(self.fake) as helpdesk:
            with RunLog(self.log_dir, run_id) as log:
                runner = Runner(
                    helpdesk=helpdesk,
                    journal=self.journal,
                    decider=self.decider,
                    log=log,
                    run_id=run_id,
                    options=options,
                    crash_hook=crash_hook,
                )
                return await runner.run()

    def log_lines(self) -> list[dict[str, object]]:
        lines: list[dict[str, object]] = []
        for path in sorted(self.log_dir.glob("*.jsonl")):
            text = path.read_text(encoding="utf-8")
            lines.extend(json.loads(line) for line in text.splitlines())
        return lines


def assert_every_ticket_answered_exactly_once(fake: FakeHelpdesk, count: int = TICKETS) -> None:
    assert len(fake.accepted_writes) == count
    assert set(fake.accepted_writes.values()) == {1}
    assert sum(fake.conflicts.values()) == 0


@pytest.fixture
def fake(clock: FakeClock) -> FakeHelpdesk:
    return FakeHelpdesk([make_ticket(number) for number in range(1, TICKETS + 1)], clock=clock)


@pytest.fixture
def harness(connect: Connect, fake: FakeHelpdesk, journal: Journal, tmp_path: Path) -> Harness:
    return Harness(connect, fake, journal, tmp_path / "logs", ScriptedDecider())
