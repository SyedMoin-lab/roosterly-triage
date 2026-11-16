import asyncio
from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.fakes.clock import FakeClock
from triage.helpdesk.pacing import Pacer


async def test_turns_are_spaced_by_the_interval() -> None:
    clock = FakeClock()
    pacer = Pacer(4.0, clock=clock, sleep=clock.sleep)
    turns = []
    for _ in range(5):
        await pacer.wait_turn()
        turns.append(clock.now)
    gaps = [later - earlier for earlier, later in pairwise(turns)]
    assert gaps == pytest.approx([0.25] * 4)


async def test_concurrent_workers_take_turns_one_interval_apart() -> None:
    clock = FakeClock()
    pacer = Pacer(4.0, clock=clock, sleep=clock.sleep)
    turns: list[float] = []

    async def worker() -> None:
        await pacer.wait_turn()
        turns.append(clock.now)

    await asyncio.gather(*(worker() for _ in range(8)))
    gaps = [later - earlier for earlier, later in pairwise(turns)]
    assert min(gaps) >= 0.25 - 1e-9


async def test_a_pause_holds_back_the_next_turn() -> None:
    clock = FakeClock()
    pacer = Pacer(4.0, clock=clock, sleep=clock.sleep)
    await pacer.wait_turn()
    paused_at = clock.now
    pacer.pause(2.0)
    await pacer.wait_turn()
    assert clock.now - paused_at >= 2.0


def test_the_rate_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        Pacer(0)


@given(
    gaps=st.lists(st.floats(min_value=0.0, max_value=2.0), min_size=1, max_size=40),
    rate=st.floats(min_value=0.5, max_value=5.0),
)
def test_no_window_of_one_second_ever_holds_more_turns_than_the_rate(
    gaps: list[float], rate: float
) -> None:
    clock = FakeClock()
    pacer = Pacer(rate, clock=clock, sleep=clock.sleep)
    turns: list[float] = []

    async def arrive_and_wait() -> None:
        for gap in gaps:
            clock.now += gap
            await pacer.wait_turn()
            turns.append(clock.now)

    asyncio.run(arrive_and_wait())
    for start in turns:
        in_window = [turn for turn in turns if start <= turn < start + 1.0]
        assert len(in_window) <= int(rate) + 1
