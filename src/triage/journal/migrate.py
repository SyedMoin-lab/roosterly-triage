import hashlib
from dataclasses import dataclass
from importlib import resources

from triage.journal.database import Pool

MIGRATION_LOCK_KEY = 7_274_310_002

_LEDGER = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    text PRIMARY KEY,
    checksum   text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


class MigrationError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Migration:
    version: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def bundled_migrations() -> list[Migration]:
    folder = resources.files("triage.journal").joinpath("migrations")
    files = sorted((entry for entry in folder.iterdir() if entry.name.endswith(".sql")), key=str)
    return [
        Migration(
            version=entry.name.removesuffix(".sql"),
            sql=entry.read_text(encoding="utf-8").replace("\r\n", "\n"),
        )
        for entry in files
    ]


async def apply_migrations(pool: Pool, migrations: list[Migration] | None = None) -> list[str]:
    pending = bundled_migrations() if migrations is None else migrations
    applied_now: list[str] = []
    async with pool.acquire() as connection, connection.transaction():
        await connection.execute("SELECT pg_advisory_xact_lock($1)", MIGRATION_LOCK_KEY)
        await connection.execute(_LEDGER)
        rows = await connection.fetch("SELECT version, checksum FROM schema_migrations")
        applied = {row["version"]: row["checksum"] for row in rows}
        for migration in pending:
            recorded = applied.get(migration.version)
            if recorded == migration.checksum:
                continue
            if recorded is not None:
                raise MigrationError(f"migration {migration.version} changed after it was applied")
            await connection.execute(migration.sql)
            await connection.execute(
                "INSERT INTO schema_migrations (version, checksum) VALUES ($1, $2)",
                migration.version,
                migration.checksum,
            )
            applied_now.append(migration.version)
    return applied_now
