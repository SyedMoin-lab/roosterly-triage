import os
import random
import uuid
from collections.abc import AsyncIterator
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest

from tests.fakes.clock import FakeClock
from tests.fakes.helpdesk import API_KEY, BASE_URL, CANDIDATE_EMAIL, Connect, FakeHelpdesk
from triage.config import HelpdeskSettings
from triage.helpdesk.client import HelpdeskClient, build_http_client
from triage.helpdesk.pacing import Pacer
from triage.journal.store import Journal, open_journal

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://triage:triage@127.0.0.1:5434/triage"
)


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
async def database_url() -> AsyncIterator[str]:
    try:
        admin = await asyncpg.connect(TEST_DATABASE_URL, timeout=5)
    except (OSError, TimeoutError, asyncpg.PostgresError) as error:
        if os.environ.get("REQUIRE_TEST_DATABASE"):
            raise
        pytest.skip(f"no Postgres at TEST_DATABASE_URL ({type(error).__name__})")
    name = f"triage_test_{uuid.uuid4().hex[:16]}"
    await admin.execute(f'CREATE DATABASE "{name}"')
    try:
        yield urlunsplit(urlsplit(TEST_DATABASE_URL)._replace(path=f"/{name}"))
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()


@pytest.fixture
async def journal(database_url: str) -> AsyncIterator[Journal]:
    async with open_journal(database_url) as opened:
        yield opened
