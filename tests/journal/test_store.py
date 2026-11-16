import asyncio
import uuid
from datetime import UTC, datetime

import pytest

from tests.fakes.decisions import HANDOFF, REPLY
from triage.domain import Ticket
from triage.journal.states import Outcome, TicketState
from triage.journal.store import Journal


def ticket(number: int) -> Ticket:
    return Ticket(id=f"T{number:03d}", received_at=datetime(2026, 10, 5, 8, number, tzinfo=UTC))


async def prepared(journal: Journal, count: int = 3) -> tuple[int, uuid.UUID]:
    epoch = await journal.start_epoch("test")
    run_id = uuid.uuid4()
    await journal.start_run(run_id, epoch, mode="live", decider="test", concurrency=1)
    await journal.add_tickets(epoch, [ticket(number) for number in range(1, count + 1)])
    return epoch, run_id


async def decided(journal: Journal, epoch: int, run_id: uuid.UUID, ticket_id: str) -> None:
    assert await journal.claim(epoch, ticket_id, run_id)
    assert await journal.record_decision(epoch, ticket_id, run_id, HANDOFF, {"decider": "test"})


async def test_epochs_count_up(journal: Journal) -> None:
    assert await journal.current_epoch() is None
    assert await journal.start_epoch("first") == 1
    assert await journal.start_epoch("reset") == 2
    assert await journal.current_epoch() == 2


async def test_adding_the_same_tickets_twice_keeps_one_row_each(journal: Journal) -> None:
    epoch, _ = await prepared(journal)
    await journal.add_tickets(epoch, [ticket(1), ticket(2)])
    assert await journal.counts(epoch) == {"new": 3}


async def test_only_one_of_many_concurrent_claims_wins(journal: Journal) -> None:
    epoch, run_id = await prepared(journal)
    results = await asyncio.gather(*(journal.claim(epoch, "T001", run_id) for _ in range(8)))
    assert results.count(True) == 1


async def test_a_recorded_decision_comes_back_exactly(journal: Journal) -> None:
    epoch, run_id = await prepared(journal)
    assert await journal.claim(epoch, "T001", run_id)
    assert await journal.record_decision(epoch, "T001", run_id, REPLY, {"decider": "test"})
    assert await journal.frozen_decision(epoch, "T001") == REPLY
    assert (await journal.states(epoch))["T001"] is TicketState.DECIDED


async def test_a_decision_needs_this_runs_claim(journal: Journal) -> None:
    epoch, run_id = await prepared(journal)
    assert not await journal.record_decision(epoch, "T001", run_id, REPLY, {})
    assert await journal.claim(epoch, "T001", run_id)
    assert not await journal.record_decision(epoch, "T001", uuid.uuid4(), REPLY, {})


async def test_posting_and_finishing_follow_the_state_machine(journal: Journal) -> None:
    epoch, run_id = await prepared(journal)
    await decided(journal, epoch, run_id, "T001")
    assert await journal.begin_posting(epoch, "T001")
    assert not await journal.begin_posting(epoch, "T001")
    posting, done = TicketState.POSTING, TicketState.DONE
    assert await journal.move(epoch, "T001", expected=posting, to=done, outcome=Outcome.POSTED)
    assert not await journal.move(epoch, "T001", expected=posting, to=done)
    assert await journal.counts(epoch) == {"done": 1, "new": 2}


async def test_claims_left_by_a_crash_are_released(journal: Journal) -> None:
    epoch, run_id = await prepared(journal)
    assert await journal.claim(epoch, "T001", run_id)
    assert await journal.release_claims(epoch) == 1
    assert (await journal.states(epoch))["T001"] is TicketState.NEW


async def test_tickets_no_longer_open_are_closed_as_handled_elsewhere(journal: Journal) -> None:
    epoch, _ = await prepared(journal)
    assert await journal.close_missing(epoch, ["T001", "T003"]) == ["T002"]
    assert (await journal.states(epoch))["T002"] is TicketState.DONE


async def test_a_failed_ticket_reopens_without_its_old_decision(journal: Journal) -> None:
    epoch, run_id = await prepared(journal)
    await decided(journal, epoch, run_id, "T001")
    assert await journal.begin_posting(epoch, "T001")
    assert await journal.move(
        epoch, "T001", expected=TicketState.POSTING, to=TicketState.FAILED, outcome=Outcome.REJECTED
    )
    assert await journal.reopen_failed(epoch, ["T001"]) == ["T001"]
    assert (await journal.states(epoch))["T001"] is TicketState.NEW
    with pytest.raises(LookupError):
        await journal.frozen_decision(epoch, "T001")


async def test_the_final_run_lock_can_be_set_and_cleared(journal: Journal) -> None:
    assert not await journal.final_run_locked()
    await journal.set_final_run_lock(locked=True, reason="final run")
    assert await journal.final_run_locked()
    await journal.set_final_run_lock(locked=False, reason="practice")
    assert not await journal.final_run_locked()
