from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class FakeClock:
    now: float = 1_800_000_000.0
    sleeps: list[float] = field(default_factory=list)

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += max(0.0, seconds)

    def utcnow(self) -> datetime:
        return datetime.fromtimestamp(self.now, UTC)
