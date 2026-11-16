import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from triage.runlog import RunLog

RUN_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def fixed_now() -> datetime:
    return datetime(2026, 11, 17, 9, 30, tzinfo=UTC)


def test_each_ticket_gets_one_json_line(tmp_path: Path) -> None:
    with RunLog(tmp_path, RUN_ID, now=fixed_now) as log:
        log.write("T001", outcome="posted", note="Één regel: geen kaartnummers")
        log.write("T002", outcome="deferred")
    assert log.path.name == "20261117T093000Z-12345678.jsonl"
    lines = [json.loads(line) for line in log.path.read_text(encoding="utf-8").splitlines()]
    assert [line["ticket_id"] for line in lines] == ["T001", "T002"]
    assert lines[0]["note"] == "Één regel: geen kaartnummers"
    assert lines[0]["run_id"] == str(RUN_ID)


def test_a_second_line_for_the_same_ticket_is_refused(tmp_path: Path) -> None:
    with RunLog(tmp_path, RUN_ID, now=fixed_now) as log:
        log.write("T001", outcome="posted")
        with pytest.raises(ValueError, match="already has a log line"):
            log.write("T001", outcome="posted")


def test_writing_before_opening_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="not open"):
        RunLog(tmp_path, RUN_ID, now=fixed_now).write("T001", outcome="posted")
