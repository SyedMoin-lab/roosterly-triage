import random
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime


def parse_retry_after(value: str | None, now: datetime) -> float | None:
    text = (value or "").strip()
    if not text:
        return None
    seconds = _as_float(text)
    if seconds is not None:
        return max(0.0, seconds)
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - now).total_seconds())


def _as_float(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 6
    base_delay: float = 0.5
    max_delay: float = 8.0
    default_retry_after: float = 1.0
    max_retry_after: float = 60.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")

    def backoff(self, retry_number: int, rng: random.Random) -> float:
        ceiling = min(self.max_delay, self.base_delay * 2 ** (retry_number - 1))
        return rng.uniform(0.0, ceiling)

    def retry_after(self, header: str | None, now: datetime) -> float:
        seconds = parse_retry_after(header, now)
        wait = self.default_retry_after if seconds is None else seconds
        return min(self.max_retry_after, wait)
