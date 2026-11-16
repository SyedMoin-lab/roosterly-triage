from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg

RUNNER_LOCK_KEY = 7_274_310_001


class RunnerAlreadyActiveError(Exception):
    pass


@asynccontextmanager
async def runner_lock(database_url: str) -> AsyncIterator[None]:
    connection = await asyncpg.connect(database_url)
    try:
        if not await connection.fetchval("SELECT pg_try_advisory_lock($1)", RUNNER_LOCK_KEY):
            raise RunnerAlreadyActiveError("another run is already active against this journal")
        yield
    finally:
        await connection.close()
