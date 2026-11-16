import asyncio
import time
from collections import deque

from triage.helpdesk.pacing import Clock, Sleep

WINDOW_SECONDS = 60.0


class RateWindow:
    def __init__(
        self,
        *,
        tokens_per_minute: int,
        requests_per_minute: int,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._tokens_per_minute = tokens_per_minute
        self._requests_per_minute = requests_per_minute
        self._clock = clock
        self._sleep = sleep
        self._spent: deque[tuple[float, int]] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int) -> None:
        tokens = min(tokens, self._tokens_per_minute)
        async with self._lock:
            while True:
                now = self._clock()
                while self._spent and now - self._spent[0][0] >= WINDOW_SECONDS:
                    self._spent.popleft()
                used = sum(cost for _, cost in self._spent)
                if (
                    len(self._spent) < self._requests_per_minute
                    and used + tokens <= self._tokens_per_minute
                ):
                    self._spent.append((now, tokens))
                    return
                await self._sleep(max(WINDOW_SECONDS - (now - self._spent[0][0]), 0.05))
