from pathlib import Path

import pytest

from triage import __version__
from triage.__main__ import format_status, main
from triage.helpdesk.models import HelpdeskStatus


def test_version_flag_prints_the_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_arguments_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "usage:" in capsys.readouterr().out


def test_status_without_configuration_says_what_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ("HELPDESK_BASE_URL", "HELPDESK_API_KEY", "CANDIDATE_EMAIL"):
        monkeypatch.delenv(name, raising=False)
    assert main(["status"]) == 2
    error = capsys.readouterr().err
    assert "HELPDESK_API_KEY" in error
    assert "CANDIDATE_EMAIL" in error


def test_the_status_line_is_readable() -> None:
    status = HelpdeskStatus(
        mode="practice", candidate="someone", open_tickets=30, handled_tickets=0
    )
    assert format_status(status) == "mode=practice candidate=someone open=30 handled=0"
