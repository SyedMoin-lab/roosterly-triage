import io
from collections import Counter
from pathlib import Path

import pytest

from tests.fakes.clock import FakeClock
from tests.fakes.helpdesk import Connect, FakeHelpdesk, Fault, make_ticket
from tests.runner.conftest import (
    TICKETS,
    Harness,
    ScriptedDecider,
    assert_every_ticket_answered_exactly_once,
)
from triage.domain import Ticket
from triage.helpdesk.errors import AuthenticationError
from triage.journal.states import Outcome
from triage.journal.store import Journal
from triage.progress import show_progress
from triage.runner import ExitCode, FinalRunLockedError, RunOptions

UNAUTHORIZED = {"error": "unauthorized", "message": "Invalid key."}
REJECTED = {"error": "validation_failed", "message": "Invalid.", "problems": ["reason"]}


async def test_a_run_answers_every_ticket_once_with_one_log_line_each(harness: Harness) -> None:
    summary = await harness.run()
    assert summary.outcomes == Counter({Outcome.POSTED: TICKETS})
    assert summary.exit_code is ExitCode.OK
    assert_every_ticket_answered_exactly_once(harness.fake)
    logged = sorted(str(line["ticket_id"]) for line in harness.log_lines())
    assert logged == [f"T{number:03d}" for number in range(1, TICKETS + 1)]
    assert await harness.journal.counts(summary.epoch) == {"done": TICKETS}


async def test_a_second_run_posts_nothing(harness: Harness) -> None:
    await harness.run()
    summary = await harness.run()
    assert summary.outcomes == Counter()
    assert_every_ticket_answered_exactly_once(harness.fake)


async def test_a_dry_run_posts_nothing_and_leaves_the_journal_untouched(harness: Harness) -> None:
    summary = await harness.run(RunOptions(dry_run=True))
    assert summary.outcomes == Counter({Outcome.PREVIEWED: TICKETS})
    assert harness.fake.accepted_writes == Counter()
    assert await harness.journal.counts(summary.epoch) == {}


async def test_the_limit_caps_how_many_tickets_are_handled(harness: Harness) -> None:
    summary = await harness.run(RunOptions(limit=5))
    assert summary.outcomes == Counter({Outcome.POSTED: 5})
    assert sorted(harness.fake.accepted_writes) == [f"T{number:03d}" for number in range(1, 6)]


async def test_a_ticket_answered_meanwhile_gets_no_second_answer(harness: Harness) -> None:
    def answer_elsewhere(ticket: Ticket) -> None:
        if ticket.id == "T005":
            harness.fake.handled["T005"] = {"action": "reply"}

    harness.decider.before_decide = answer_elsewhere
    summary = await harness.run()
    assert summary.outcomes[Outcome.ALREADY_HANDLED] == 1
    assert harness.fake.accepted_writes["T005"] == 0


async def test_a_lost_response_is_settled_by_reading_not_by_resending(harness: Harness) -> None:
    harness.fake.inject("POST", "/tickets/T007/handoff", Fault("lost_response"))
    summary = await harness.run()
    assert summary.outcomes[Outcome.CONFIRMED_BY_READ] == 1
    assert_every_ticket_answered_exactly_once(harness.fake)


async def test_an_unavailable_helpdesk_defers_the_ticket_to_the_next_run(harness: Harness) -> None:
    harness.fake.inject("POST", "/tickets/T003/handoff", *[Fault("status", 503)] * 6)
    first = await harness.run()
    assert first.outcomes[Outcome.DEFERRED] == 1
    assert first.exit_code is ExitCode.INCOMPLETE
    second = await harness.run()
    assert second.outcomes == Counter({Outcome.POSTED: 1})
    assert harness.decider.calls["T003"] == 1
    assert_every_ticket_answered_exactly_once(harness.fake)


async def test_random_503s_still_give_one_answer_per_ticket(
    connect: Connect, clock: FakeClock, journal: Journal, tmp_path: Path
) -> None:
    fake = FakeHelpdesk(
        [make_ticket(number) for number in range(1, TICKETS + 1)],
        clock=clock,
        random_503_rate=0.25,
        seed=5,
    )
    harness = Harness(connect, fake, journal, tmp_path, ScriptedDecider())
    for _ in range(3):
        await harness.run()
    assert fake.statuses[503] > 0
    assert_every_ticket_answered_exactly_once(fake)


async def test_a_reset_outside_the_agent_starts_a_new_epoch(harness: Harness) -> None:
    first = await harness.run()
    harness.fake.handled.clear()
    second = await harness.run()
    assert second.epoch == first.epoch + 1
    assert second.outcomes == Counter({Outcome.POSTED: TICKETS})
    assert set(harness.fake.accepted_writes.values()) == {2}
    assert sum(harness.fake.conflicts.values()) == 0


async def test_tickets_answered_elsewhere_are_closed_out(harness: Harness) -> None:
    await harness.run(RunOptions(limit=5))
    harness.fake.handled["T010"] = {"action": "reply"}
    summary = await harness.run()
    assert summary.outcomes[Outcome.HANDLED_ELSEWHERE] == 1
    assert summary.outcomes[Outcome.POSTED] == TICKETS - 6
    assert harness.fake.accepted_writes["T010"] == 0


async def test_the_final_run_lock_refuses_live_runs_but_allows_a_dry_run(harness: Harness) -> None:
    await harness.journal.set_final_run_lock(locked=True, reason="final run")
    with pytest.raises(FinalRunLockedError):
        await harness.run()
    summary = await harness.run(RunOptions(dry_run=True, limit=2))
    assert summary.outcomes == Counter({Outcome.PREVIEWED: 2})
    assert harness.fake.accepted_writes == Counter()


async def test_a_provider_outage_leaves_tickets_open_and_exits_with_code_3(
    harness: Harness,
) -> None:
    harness.decider.outage = True
    summary = await harness.run()
    assert summary.exit_code is ExitCode.PROVIDER_DOWN
    assert harness.fake.accepted_writes == Counter()
    assert await harness.journal.counts(summary.epoch) == {"new": TICKETS}


async def test_a_decider_bug_on_one_ticket_does_not_stop_the_others(harness: Harness) -> None:
    harness.decider.failing = frozenset({"T002"})
    summary = await harness.run()
    assert summary.outcomes == Counter({Outcome.POSTED: TICKETS - 1, Outcome.DECIDE_FAILED: 1})
    assert summary.exit_code is ExitCode.INCOMPLETE


async def test_a_rejected_decision_fails_and_is_decided_again_next_run(harness: Harness) -> None:
    harness.fake.inject("POST", "/tickets/T004/handoff", Fault("status", 422, body=REJECTED))
    first = await harness.run()
    assert first.outcomes[Outcome.REJECTED] == 1
    second = await harness.run()
    assert second.outcomes == Counter({Outcome.POSTED: 1})
    assert harness.decider.calls["T004"] == 2
    assert_every_ticket_answered_exactly_once(harness.fake)


async def test_a_refused_key_stops_the_run_and_keeps_the_frozen_decision(harness: Harness) -> None:
    harness.fake.inject("POST", "/tickets/T001/handoff", Fault("status", 401, body=UNAUTHORIZED))
    with pytest.raises(AuthenticationError):
        await harness.run(RunOptions(concurrency=1))
    await harness.run(RunOptions(concurrency=1))
    assert harness.decider.calls["T001"] == 1
    assert_every_ticket_answered_exactly_once(harness.fake)


async def test_the_progress_shows_each_ticket_starting_and_being_posted(harness: Harness) -> None:
    stream = io.StringIO()
    with show_progress(stream):
        await harness.run(RunOptions(limit=2))
    lines = stream.getvalue().splitlines()
    assert lines[0].endswith("2 open tickets to handle, 4 at a time")
    for ticket_id in ("T001", "T002"):
        mine = [line for line in lines if f" {ticket_id} " in line]
        assert mine[0].split(ticket_id, 1)[1].strip().startswith("started: ")
        assert mine[-1].split(ticket_id, 1)[1].strip().startswith("posted: handoff, ")
