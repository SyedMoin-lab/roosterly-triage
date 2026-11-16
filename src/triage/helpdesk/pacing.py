import asyncio
import time
from collections.abc import Awaitable, Callable

type Clock = Callable[[], float]
type Sleep = Callable[[float], Awaitable[None]]


class Pacer:
    def __init__(
        self,
        requests_per_second: float,
        *,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        self._interval = 1.0 / requests_per_second
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._last_turn = float("-inf")
        self._paused_until = float("-inf")

    async def wait_turn(self) -> None:
        async with self._lock:
            while (delay := self._ready_at() - self._clock()) > 0:
                await self._sleep(delay)
            self._last_turn = self._clock()

    def pause(self, seconds: float) -> None:
        self._paused_until = max(self._paused_until, self._clock() + seconds)

    def _ready_at(self) -> float:
        return max(self._last_turn + self._interval, self._paused_until)
