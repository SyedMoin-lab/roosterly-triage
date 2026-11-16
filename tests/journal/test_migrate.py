from collections.abc import AsyncIterator

import asyncpg
import pytest

from triage.journal.database import Pool
from triage.journal.migrate import (
    Migration,
    MigrationError,
    apply_migrations,
    bundled_migrations,
)


@pytest.fixture
async def pool(database_url: str) -> AsyncIterator[Pool]:
    created = await asyncpg.create_pool(database_url, min_size=1, max_size=2)
    try:
        yield created
    finally:
        await created.close()


def test_bundled_migrations_are_found_in_version_order() -> None:
    versions = [migration.version for migration in bundled_migrations()]
    assert versions[0] == "0001_journal"
    assert versions == sorted(versions)


async def test_migrations_apply_once(pool: Pool) -> None:
    first = await apply_migrations(pool)
    second = await apply_migrations(pool)
    assert first == [migration.version for migration in bundled_migrations()]
    assert second == []


async def test_a_migration_changed_after_it_was_applied_is_refused(pool: Pool) -> None:
    await apply_migrations(pool, [Migration("0001_demo", "CREATE TABLE demo (id int)")])
    with pytest.raises(MigrationError, match="changed after it was applied"):
        await apply_migrations(pool, [Migration("0001_demo", "CREATE TABLE demo (id bigint)")])
