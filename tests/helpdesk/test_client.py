import asyncio
import time
from datetime import timedelta
from email.utils import format_datetime

import pytest
from pydantic import SecretStr

from tests.fakes.clock import FakeClock
from tests.fakes.decisions import CLOSE, HANDOFF, REPLY
from tests.fakes.helpdesk import API_KEY, CANDIDATE_EMAIL, FakeHelpdesk, Fault, make_ticket
from tests.helpdesk.conftest import Connect
from triage.config import HelpdeskSettings
from triage.helpdesk.client import HelpdeskClient, build_http_client
from triage.helpdesk.errors import (
    AlreadyHandledError,
    AuthenticationError,
    NotFoundError,
    ProtocolViolationError,
    RequestRejectedError,
    ServiceUnavailableError,
    ValidationFailedError,
    WriteOutcomeUnknownError,
)
from triage.helpdesk.pacing import Pacer


async def test_every_request_carries_the_key_and_the_candidate_email(
    settings: HelpdeskSettings,
) -> None:
    http = build_http_client(settings)
    assert http.headers["Authorization"] == f"Bearer {API_KEY}"
    assert http.headers["X-Candidate-Email"] == CANDIDATE_EMAIL
    await http.aclose()


async def test_status_reports_the_mode_and_ticket_counts(client: HelpdeskClient) -> None:
    status = await client.status()
    assert (status.mode, status.open_tickets, status.handled_tickets) == ("practice", 25, 0)


async def test_open_tickets_follows_the_cursor_to_the_last_page(
    client: HelpdeskClient, helpdesk: FakeHelpdesk
) -> None:
    tickets = await client.open_tickets()
    assert [ticket.id for ticket in tickets] == [f"T{number:03d}" for number in range(1, 26)]
    assert helpdesk.requests_to("GET", "/tickets") == 3


async def test_open_tickets_leaves_out_handled_tickets(
    client: HelpdeskClient, helpdesk: FakeHelpdesk
) -> None:
    helpdesk.handled.update({"T002": {"action": "close"}, "T011": {"action": "close"}})
    ids = [ticket.id for ticket in await client.open_tickets()]
    assert len(ids) == 23
    assert "T002" not in ids
    assert "T011" not in ids


async def test_a_repeating_cursor_is_a_protocol_violation(
    client: HelpdeskClient, helpdesk: FakeHelpdesk
) -> None:
    helpdesk.stuck_cursor = "T005"
    with pytest.raises(ProtocolViolationError, match="cursor repeated"):
        await client.open_tickets()


async def test_a_ticket_with_an_unsafe_id_in_the_response_is_refused(
    connect: Connect, clock: FakeClock
) -> None:
    fake = FakeHelpdesk([make_ticket(1, id="../practice/reset")], clock=clock)
    async with connect(fake) as client:
        with pytest.raises(ProtocolViolationError, match="unexpected shape"):
            await client.open_tickets()


@pytest.mark.parametrize(
    "ticket_id", ["../practice/reset", "T001/close", "", "T 001", "T001?x=1", "T001#"]
)
async def test_unsafe_ticket_ids_never_reach_the_network(
    client: HelpdeskClient, helpdesk: FakeHelpdesk, ticket_id: str
) -> None:
    with pytest.raises(ValueError, match="unsafe ticket id"):
        await client.submit(ticket_id, REPLY)
    with pytest.raises(ValueError, match="unsafe ticket id"):
        await client.ticket(ticket_id)
    assert helpdesk.received == []


async def test_a_submitted_decision_is_recorded_once_and_shows_as_handled(
    client: HelpdeskClient, helpdesk: FakeHelpdesk
) -> None:
    assert not (await client.ticket("T001")).is_handled
    await client.submit("T001", REPLY)
    assert helpdesk.accepted_writes["T001"] == 1
    assert helpdesk.handled["T001"]["draft_reply"] == REPLY.draft_reply
    assert (await client.ticket("T001")).is_handled


async def test_examples_come_back_with_their_labels(connect: Connect, clock: FakeClock) -> None:
    from tests.fakes.helpdesk import make_example

    fake = FakeHelpdesk([], clock=clock, examples=[make_example(1, action="handoff")])
    async with connect(fake) as client:
        examples = await client.examples()
    assert [(example.id, example.label.action) for example in examples] == [("E01", "handoff")]


async def test_a_503_on_a_read_is_retried_until_it_succeeds(
    client: HelpdeskClient, helpdesk: FakeHelpdesk
) -> None:
    helpdesk.inject("GET", "/status", Fault("status", 503), Fault("status", 503))
    await client.status()
    assert helpdesk.requests_to("GET", "/status") == 3


async def test_a_503_on_a_write_is_retried_and_saved_exactly_once(
    client: HelpdeskClient, helpdesk: FakeHelpdesk
) -> None:
    helpdesk.inject("POST", "/tickets/T001/handoff", Fault("status", 503), Fault("status", 503))
    await client.submit("T001", HANDOFF)
    assert helpdesk.requests_to("POST", "/tickets/T001/handoff") == 3
    assert helpdesk.accepted_writes["T001"] == 1


async def test_persistent_503s_give_up_after_the_retry_budget(
    client: HelpdeskClient, helpdesk: FakeHelpdesk
) -> None:
    helpdesk.inject("GET", "/status", *[Fault("status", 503)] * 6)
    with pytest.raises(ServiceUnavailableError):
        await client.status()
    assert helpdesk.requests_to("GET", "/status") == 6


async def test_a_429_waits_for_the_retry_after_seconds(
    client: HelpdeskClient, helpdesk: FakeHelpdesk, clock: FakeClock
) -> None:
    helpdesk.inject("GET", "/status", Fault("status", 429, headers={"Retry-After": "3"}))
    started = clock.now
    await client.status()
    assert clock.now - started >= 3.0


async def test_a_429_accepts_an_http_date_retry_after(
    client: HelpdeskClient, helpdesk: FakeHelpdesk, clock: FakeClock
) -> None:
    retry_at = format_datetime(clock.utcnow() + timedelta(seconds=5), usegmt=True)
    helpdesk.inject("GET", "/status", Fault("status", 429, headers={"Retry-After": retry_at}))
    started = clock.now
    await client.status()
    assert clock.now - started >= 5.0


async def test_a_long_retry_after_is_capped(
    client: HelpdeskClient, helpdesk: FakeHelpdesk, clock: FakeClock
) -> None:
    helpdesk.inject("GET", "/status", Fault("status", 429, headers={"Retry-After": "3600"}))
    started = clock.now
    await client.status()
    assert 60.0 <= clock.now - started < 61.0


async def test_a_409_is_reported_and_never_retried(
    client: HelpdeskClient, helpdesk: FakeHelpdesk
) -> None:
    helpdesk.handled["T001"] = {"action": "close"}
    with pytest.raises(AlreadyHandledError):
        await client.submit("T001", CLOSE)
    assert helpdesk.requests_to("POST", "/tickets/T001/close") == 1
    assert helpdesk.conflicts["T001"] == 1


async def test_a_wrong_key_stops_at_the_first_401(
    connect: Connect, helpdesk: FakeHelpdesk, settings: HelpdeskSettings
) -> None:
    wrong = settings.model_copy(update={"helpdesk_api_key": SecretStr("wrong-key")})
    async with connect(helpdesk, wrong) as client:
        with pytest.raises(AuthenticationError, match="401"):
            await client.status()
    assert helpdesk.requests_to("GET", "/status") == 1


async def test_an_unknown_ticket_is_not_found(client: HelpdeskClient) -> None:
    with pytest.raises(NotFoundError, match="404"):
        await client.ticket("T999")


async def test_a_422_carries_the_problems_and_is_not_retried(
    client: HelpdeskClient, helpdesk: FakeHelpdesk
) -> None:
    body = {"error": "validation_failed", "message": "Invalid.", "problems": ["reason is required"]}
    helpdesk.inject("POST", "/tickets/T001/reply", Fault("status", 422, body=body))
    with pytest.raises(ValidationFailedError) as caught:
        await client.submit("T001", REPLY)
    assert caught.value.problems == ["reason is required"]
    assert helpdesk.requests_to("POST", "/tickets/T001/reply") == 1


async def test_a_400_is_rejected_without_retrying(
    client: HelpdeskClient, helpdesk: FakeHelpdesk
) -> None:
    body = {"error": "missing_email", "message": "Send the X-Candidate-Email header."}
    helpdesk.inject("GET", "/status", Fault("status", 400, body=body))
    with pytest.raises(RequestRejectedError) as caught:
        await client.status()
    assert caught.value.code == "missing_email"
    assert helpdesk.requests_to("GET", "/status") == 1


async def test_a_lost_response_to_a_write_is_reported_as_unknown_and_not_resent(
    client: HelpdeskClient, helpdesk: FakeHelpdesk
) -> None:
    helpdesk.inject("POST", "/tickets/T001/reply", Fault("lost_response"))
    with pytest.raises(WriteOutcomeUnknownError):
        await client.submit("T001", REPLY)
    assert helpdesk.requests_to("POST", "/tickets/T001/reply") == 1
    assert helpdesk.accepted_writes["T001"] == 1
    assert (await client.ticket("T001")).is_handled


async def test_a_read_that_times_out_is_retried(
    client: HelpdeskClient, helpdesk: FakeHelpdesk
) -> None:
    helpdesk.inject("GET", "/status", Fault("timeout_before_processing"))
    status = await client.status()
    assert status.open_tickets == 25


async def test_a_write_that_never_connected_is_retried_safely(
    client: HelpdeskClient, helpdesk: FakeHelpdesk
) -> None:
    helpdesk.inject("POST", "/tickets/T001/reply", Fault("connect_error"))
    await client.submit("T001", REPLY)
    assert helpdesk.accepted_writes["T001"] == 1


async def test_an_html_502_on_a_read_is_retried(
    client: HelpdeskClient, helpdesk: FakeHelpdesk
) -> None:
    helpdesk.inject("GET", "/status", Fault("html", 502))
    await client.status()
    assert helpdesk.requests_to("GET", "/status") == 2


async def test_an_html_502_on_a_write_is_an_unknown_outcome(
    client: HelpdeskClient, helpdesk: FakeHelpdesk
) -> None:
    helpdesk.inject("POST", "/tickets/T001/reply", Fault("html", 502))
    with pytest.raises(WriteOutcomeUnknownError):
        await client.submit("T001", REPLY)
    assert helpdesk.requests_to("POST", "/tickets/T001/reply") == 1


async def test_random_503s_never_cause_a_lost_or_double_decision(
    connect: Connect, clock: FakeClock
) -> None:
    fake = FakeHelpdesk(
        [make_ticket(number) for number in range(1, 31)],
        clock=clock,
        random_503_rate=0.3,
        seed=11,
    )
    async with connect(fake) as client:
        for ticket in await client.open_tickets():
            await client.submit(ticket.id, HANDOFF)
    assert fake.statuses[503] > 0
    assert set(fake.accepted_writes.values()) == {1}
    assert len(fake.accepted_writes) == 30
    assert sum(fake.conflicts.values()) == 0


async def test_parallel_workers_stay_under_the_rate_limit(settings: HelpdeskSettings) -> None:
    fake = FakeHelpdesk(
        [make_ticket(number) for number in range(1, 11)],
        clock=time.monotonic,
        window_seconds=0.1,
    )
    http = build_http_client(settings, transport=fake.transport())
    async with HelpdeskClient(http, pacer=Pacer(30.0)) as client:
        await asyncio.gather(
            *(client.ticket(f"T{number:03d}") for number in range(1, 11) for _ in range(3))
        )
    assert fake.statuses[429] == 0
    assert fake.busiest_window() <= 5
