from collections.abc import AsyncIterator

import pytest

from tests.fakes.clock import FakeClock
from tests.fakes.helpdesk import Connect, FakeHelpdesk, make_ticket
from triage.helpdesk.client import HelpdeskClient


@pytest.fixture
def helpdesk(clock: FakeClock) -> FakeHelpdesk:
    return FakeHelpdesk([make_ticket(number) for number in range(1, 26)], clock=clock)


@pytest.fixture
async def client(connect: Connect, helpdesk: FakeHelpdesk) -> AsyncIterator[HelpdeskClient]:
    async with connect(helpdesk) as connected:
        yield connected
