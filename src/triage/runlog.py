import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Self
from uuid import UUID

from triage.safety.redaction import scrub


class RunLog:
    def __init__(
        self,
        directory: Path,
        run_id: UUID,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.path = directory / f"{now().strftime('%Y%m%dT%H%M%SZ')}-{run_id.hex[:8]}.jsonl"
        self._directory = directory
        self._run_id = run_id
        self._now = now
        self._written: set[str] = set()
        self._file: IO[str] | None = None

    def __enter__(self) -> Self:
        self._directory.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a", encoding="utf-8", newline="\n")
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def write(self, ticket_id: str, **fields: object) -> None:
        if self._file is None:
            raise RuntimeError("the run log is not open")
        if ticket_id in self._written:
            raise ValueError(f"ticket {ticket_id} already has a log line in this run")
        self._written.add(ticket_id)
        line = {
            "ts": self._now().isoformat(timespec="milliseconds"),
            "run_id": str(self._run_id),
            "ticket_id": ticket_id,
            **{key: scrub(value) for key, value in fields.items()},
        }
        self._file.write(json.dumps(line, ensure_ascii=False) + "\n")
        self._file.flush()
