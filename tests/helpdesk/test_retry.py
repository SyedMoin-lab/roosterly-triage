import random
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from triage.helpdesk.retry import RetryPolicy, parse_retry_after

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("header", "expected"),
    [("3", 3.0), ("1.5", 1.5), (" 2 ", 2.0), ("-4", 0.0), ("0", 0.0)],
)
def test_seconds_are_parsed(header: str, expected: float) -> None:
    assert parse_retry_after(header, NOW) == expected


def test_an_http_date_in_the_future_becomes_the_seconds_until_then() -> None:
    header = format_datetime(NOW + timedelta(seconds=7), usegmt=True)
    assert parse_retry_after(header, NOW) == 7.0


def test_an_http_date_in_the_past_means_no_wait() -> None:
    header = format_datetime(NOW - timedelta(minutes=5), usegmt=True)
    assert parse_retry_after(header, NOW) == 0.0


@pytest.mark.parametrize("header", [None, "", "   ", "soon", "Tuesday-ish"])
def test_missing_or_unreadable_values_give_none(header: str | None) -> None:
    assert parse_retry_after(header, NOW) is None


def test_the_policy_falls_back_to_a_default_and_caps_long_waits() -> None:
    policy = RetryPolicy(default_retry_after=1.0, max_retry_after=60.0)
    assert policy.retry_after(None, NOW) == 1.0
    assert policy.retry_after("5", NOW) == 5.0
    assert policy.retry_after("3600", NOW) == 60.0


def test_at_least_one_attempt_is_required() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        RetryPolicy(max_attempts=0)


@given(retry_number=st.integers(min_value=1, max_value=30), seed=st.integers())
def test_backoff_stays_within_its_exponential_ceiling(retry_number: int, seed: int) -> None:
    policy = RetryPolicy(base_delay=0.5, max_delay=8.0)
    delay = policy.backoff(retry_number, random.Random(seed))
    assert 0.0 <= delay <= min(8.0, 0.5 * 2 ** (retry_number - 1))
