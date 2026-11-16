import pytest
from hypothesis import given
from hypothesis import strategies as st

from triage.evaluation.stats import mcnemar_exact, wilson_interval


def test_wilson_interval_matches_the_textbook_value() -> None:
    low, high = wilson_interval(8, 10)
    assert low == pytest.approx(0.490, abs=0.001)
    assert high == pytest.approx(0.943, abs=0.001)


def test_an_empty_sample_says_nothing() -> None:
    assert wilson_interval(0, 0) == (0.0, 1.0)


@given(total=st.integers(min_value=1, max_value=500), data=st.data())
def test_the_interval_always_contains_the_observed_share(total: int, data: st.DataObject) -> None:
    successes = data.draw(st.integers(min_value=0, max_value=total))
    low, high = wilson_interval(successes, total)
    share = successes / total
    assert 0.0 <= low <= share + 1e-9
    assert share - 1e-9 <= high <= 1.0


def test_mcnemar_is_one_without_changes_and_small_for_a_one_sided_shift() -> None:
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(1, 1) == 1.0
    assert mcnemar_exact(6, 0) == pytest.approx(0.03125)
