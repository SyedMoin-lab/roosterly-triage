import json
from collections.abc import AsyncIterator, Iterable, Mapping
from contextlib import asynccontextmanager
from uuid import UUID

import asyncpg

from triage.domain import Decision, Ticket
from triage.journal.database import Pool
from triage.journal.migrate import apply_migrations
from triage.journal.states import Outcome, TicketState


class Journal:
    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    @property
    def pool(self) -> Pool:
        return self._pool

    async def current_epoch(self) -> int | None:
        value = await self._pool.fetchval("SELECT max(epoch) FROM epochs")
        return None if value is None else int(value)

    async def start_epoch(self, reason: str) -> int:
        value = await self._pool.fetchval(
            "INSERT INTO epochs (epoch, reason) "
            "SELECT coalesce(max(epoch), 0) + 1, $1 FROM epochs RETURNING epoch",
            reason,
        )
        return int(value)

    async def start_run(
        self, run_id: UUID, epoch: int, *, mode: str, decider: str, concurrency: int
    ) -> None:
        await self._pool.execute(
            "INSERT INTO runs (run_id, epoch, mode, decider, concurrency) "
            "VALUES ($1, $2, $3, $4, $5)",
            run_id,
            epoch,
            mode,
            decider,
            concurrency,
        )

    async def finish_run(self, run_id: UUID, *, exit_code: int, summary: Mapping[str, int]) -> None:
        await self._pool.execute(
            "UPDATE runs SET finished_at = now(), exit_code = $2, summary = $3::jsonb "
            "WHERE run_id = $1",
            run_id,
            exit_code,
            json.dumps(dict(summary)),
        )

    async def add_tickets(self, epoch: int, tickets: Iterable[Ticket]) -> None:
        await self._pool.executemany(
            "INSERT INTO tickets (epoch, ticket_id, received_at) VALUES ($1, $2, $3) "
            "ON CONFLICT DO NOTHING",
            [(epoch, ticket.id, ticket.received_at) for ticket in tickets],
        )

    async def states(self, epoch: int) -> dict[str, TicketState]:
        rows = await self._pool.fetch(
            "SELECT ticket_id, state FROM tickets WHERE epoch = $1", epoch
        )
        return {row["ticket_id"]: TicketState(row["state"]) for row in rows}

    async def ids_in_state(self, epoch: int, state: TicketState) -> list[str]:
        rows = await self._pool.fetch(
            "SELECT ticket_id FROM tickets WHERE epoch = $1 AND state = $2 "
            "ORDER BY received_at, ticket_id",
            epoch,
            state.value,
        )
        return [row["ticket_id"] for row in rows]

    async def counts(self, epoch: int) -> dict[str, int]:
        rows = await self._pool.fetch(
            "SELECT state, count(*) AS tickets FROM tickets WHERE epoch = $1 GROUP BY state",
            epoch,
        )
        return {row["state"]: int(row["tickets"]) for row in rows}

    async def release_claims(self, epoch: int) -> int:
        status = await self._pool.execute(
            "UPDATE tickets SET state = 'new', claimed_by = NULL, updated_at = now() "
            "WHERE epoch = $1 AND state = 'deciding'",
            epoch,
        )
        return _row_count(status)

    async def close_missing(self, epoch: int, open_ids: Iterable[str]) -> list[str]:
        rows = await self._pool.fetch(
            "UPDATE tickets SET state = 'done', outcome = 'handled_elsewhere', updated_at = now() "
            "WHERE epoch = $1 AND state IN ('new', 'decided') "
            "AND NOT (ticket_id = ANY($2::text[])) RETURNING ticket_id",
            epoch,
            list(open_ids),
        )
        return [row["ticket_id"] for row in rows]

    async def reopen_failed(self, epoch: int, open_ids: Iterable[str]) -> list[str]:
        async with self._pool.acquire() as connection, connection.transaction():
            rows = await connection.fetch(
                "UPDATE tickets SET state = 'new', outcome = NULL, claimed_by = NULL, "
                "updated_at = now() "
                "WHERE epoch = $1 AND state = 'failed' AND ticket_id = ANY($2::text[]) "
                "RETURNING ticket_id",
                epoch,
                list(open_ids),
            )
            reopened = [row["ticket_id"] for row in rows]
            await connection.execute(
                "DELETE FROM decisions WHERE epoch = $1 AND ticket_id = ANY($2::text[])",
                epoch,
                reopened,
            )
        return reopened

    async def claim(self, epoch: int, ticket_id: str, run_id: UUID) -> bool:
        status = await self._pool.execute(
            "UPDATE tickets SET state = 'deciding', claimed_by = $3, updated_at = now() "
            "WHERE epoch = $1 AND ticket_id = $2 AND state = 'new'",
            epoch,
            ticket_id,
            run_id,
        )
        return _row_count(status) == 1

    async def record_decision(
        self,
        epoch: int,
        ticket_id: str,
        run_id: UUID,
        decision: Decision,
        trace: Mapping[str, object],
    ) -> bool:
        async with self._pool.acquire() as connection, connection.transaction():
            status = await connection.execute(
                "UPDATE tickets SET state = 'decided', updated_at = now() "
                "WHERE epoch = $1 AND ticket_id = $2 AND state = 'deciding' AND claimed_by = $3",
                epoch,
                ticket_id,
                run_id,
            )
            if _row_count(status) != 1:
                return False
            await connection.execute(
                "INSERT INTO decisions (epoch, ticket_id, run_id, action, body, trace) "
                "VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb)",
                epoch,
                ticket_id,
                run_id,
                decision.action.value,
                decision.model_dump_json(),
                json.dumps(dict(trace), default=str),
            )
        return True

    async def frozen_decision(self, epoch: int, ticket_id: str) -> Decision:
        body = await self._pool.fetchval(
            "SELECT body FROM decisions WHERE epoch = $1 AND ticket_id = $2", epoch, ticket_id
        )
        if body is None:
            raise LookupError(f"no frozen decision for {ticket_id} in epoch {epoch}")
        return Decision.model_validate_json(body)

    async def begin_posting(self, epoch: int, ticket_id: str) -> bool:
        status = await self._pool.execute(
            "UPDATE tickets SET state = 'posting', post_attempts = post_attempts + 1, "
            "updated_at = now() WHERE epoch = $1 AND ticket_id = $2 AND state = 'decided'",
            epoch,
            ticket_id,
        )
        return _row_count(status) == 1

    async def move(
        self,
        epoch: int,
        ticket_id: str,
        *,
        expected: TicketState,
        to: TicketState,
        outcome: Outcome | None = None,
    ) -> bool:
        status = await self._pool.execute(
            "UPDATE tickets SET state = $4, outcome = coalesce($5, outcome), updated_at = now() "
            "WHERE epoch = $1 AND ticket_id = $2 AND state = $3",
            epoch,
            ticket_id,
            expected.value,
            to.value,
            None if outcome is None else outcome.value,
        )
        return _row_count(status) == 1

    async def final_run_locked(self) -> bool:
        value = await self._pool.fetchval("SELECT value FROM control WHERE name = 'final_run_lock'")
        return value is not None and json.loads(value).get("locked") is True

    async def set_final_run_lock(self, *, locked: bool, reason: str) -> None:
        await self._pool.execute(
            "INSERT INTO control (name, value) VALUES ('final_run_lock', $1::jsonb) "
            "ON CONFLICT (name) DO UPDATE SET value = excluded.value, updated_at = now()",
            json.dumps({"locked": locked, "reason": reason}),
        )


@asynccontextmanager
async def open_journal(
    database_url: str, *, max_connections: int = 10, migrate: bool = True
) -> AsyncIterator[Journal]:
    pool = await asyncpg.create_pool(
        database_url, min_size=1, max_size=max_connections, command_timeout=30
    )
    try:
        if migrate:
            await apply_migrations(pool)
        yield Journal(pool)
    finally:
        await pool.close()


def _row_count(status: str) -> int:
    return int(status.rsplit(" ", 1)[-1])
