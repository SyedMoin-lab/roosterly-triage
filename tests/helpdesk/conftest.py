import random
from collections.abc import AsyncIterator, Callable

import pytest

from tests.fakes.clock import FakeClock
from tests.fakes.helpdesk import API_KEY, BASE_URL, CANDIDATE_EMAIL, FakeHelpdesk, make_ticket
from triage.config import HelpdeskSettings
from triage.helpdesk.client import HelpdeskClient, build_http_client
from triage.helpdesk.pacing import Pacer

type Connect = Callable[..., HelpdeskClient]


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def settings() -> HelpdeskSettings:
    return HelpdeskSettings.model_validate(
        {
            "helpdesk_base_url": BASE_URL,
            "helpdesk_api_key": API_KEY,
            "candidate_email": CANDIDATE_EMAIL,
        }
    )


@pytest.fixture
def helpdesk(clock: FakeClock) -> FakeHelpdesk:
    return FakeHelpdesk([make_ticket(number) for number in range(1, 26)], clock=clock)


@pytest.fixture
def connect(clock: FakeClock, settings: HelpdeskSettings) -> Connect:
    def _connect(
        fake: FakeHelpdesk, connect_settings: HelpdeskSettings | None = None
    ) -> HelpdeskClient:
        chosen = connect_settings or settings
        pacer = Pacer(chosen.helpdesk_requests_per_second, clock=clock, sleep=clock.sleep)
        return HelpdeskClient(
            build_http_client(chosen, transport=fake.transport()),
            pacer=pacer,
            sleep=clock.sleep,
            rng=random.Random(7),
            now=clock.utcnow,
        )

    return _connect


@pytest.fixture
async def client(connect: Connect, helpdesk: FakeHelpdesk) -> AsyncIterator[HelpdeskClient]:
    async with connect(helpdesk) as connected:
        yield connected
