import pytest

from tests.fakes.helpdesk import Fault
from tests.runner.conftest import (
    TICKETS,
    Harness,
    SimulatedCrash,
    assert_every_ticket_answered_exactly_once,
    crash_at,
)
from triage.journal.states import Outcome
from triage.runner import ExitCode, RunOptions

CRASH_POINTS = ("after_claim", "after_decision", "after_posting_claim", "after_post")


@pytest.mark.parametrize("concurrency", [1, 4])
@pytest.mark.parametrize("ticket_id", ["T001", "T015", "T030"])
@pytest.mark.parametrize("point", CRASH_POINTS)
async def test_a_crash_at_any_point_never_loses_or_repeats_an_answer(
    harness: Harness, point: str, ticket_id: str, concurrency: int
) -> None:
    options = RunOptions(concurrency=concurrency)
    with pytest.raises(SimulatedCrash):
        await harness.run(options, crash_at(point, ticket_id))
    summary = await harness.run(options)
    assert summary.exit_code is ExitCode.OK
    assert_every_ticket_answered_exactly_once(harness.fake)
    assert await harness.journal.counts(summary.epoch) == {"done": TICKETS}


async def test_a_frozen_decision_is_reused_after_a_crash(harness: Harness) -> None:
    with pytest.raises(SimulatedCrash):
        await harness.run(RunOptions(concurrency=1), crash_at("after_decision", "T001"))
    await harness.run(RunOptions(concurrency=1))
    assert harness.decider.calls["T001"] == 1
    assert_every_ticket_answered_exactly_once(harness.fake)


async def test_a_crash_after_the_post_is_settled_by_reading(harness: Harness) -> None:
    with pytest.raises(SimulatedCrash):
        await harness.run(RunOptions(concurrency=1), crash_at("after_post", "T001"))
    summary = await harness.run(RunOptions(concurrency=1))
    assert summary.outcomes[Outcome.CONFIRMED_BY_READ] == 1
    assert harness.fake.accepted_writes["T001"] == 1


async def test_a_post_is_never_resent_while_the_helpdesk_cannot_be_read(harness: Harness) -> None:
    with pytest.raises(SimulatedCrash):
        await harness.run(RunOptions(concurrency=1), crash_at("after_posting_claim", "T001"))
    harness.fake.inject("GET", "/tickets/T001", *[Fault("status", 503)] * 6)
    unsettled = await harness.run(RunOptions(concurrency=1))
    assert unsettled.outcomes[Outcome.UNSETTLED] == 1
    assert harness.fake.accepted_writes["T001"] == 0
    await harness.run(RunOptions(concurrency=1))
    assert_every_ticket_answered_exactly_once(harness.fake)
