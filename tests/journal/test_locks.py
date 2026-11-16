import pytest

from triage.journal.locks import RunnerAlreadyActiveError, runner_lock


async def test_a_second_runner_is_refused_while_the_first_holds_the_lock(database_url: str) -> None:
    async with runner_lock(database_url):
        with pytest.raises(RunnerAlreadyActiveError):
            async with runner_lock(database_url):
                pass


async def test_the_lock_is_free_again_after_the_first_runner_ends(database_url: str) -> None:
    async with runner_lock(database_url):
        pass
    async with runner_lock(database_url):
        pass
