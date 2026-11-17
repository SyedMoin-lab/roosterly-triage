import pytest

from triage.llm.roster import (
    DRAFTING_MODELS,
    JUDGING_MODELS,
    TRIAGE_MODELS,
    VERIFYING_MODELS,
    VOTING_MODELS,
    ModelSpec,
    other_families,
)


def _name(spec: ModelSpec) -> str:
    return spec.short_name


@pytest.mark.parametrize("triage", TRIAGE_MODELS, ids=_name)
def test_both_votes_come_from_two_other_model_families(triage: ModelSpec) -> None:
    voters = other_families(VOTING_MODELS, triage.family)[:2]
    families = {voter.family for voter in voters}
    assert len(families) == 2
    assert triage.family not in families


@pytest.mark.parametrize("drafter", DRAFTING_MODELS, ids=_name)
def test_a_draft_is_verified_by_another_model_family(drafter: ModelSpec) -> None:
    verifiers = other_families(VERIFYING_MODELS, drafter.family)
    assert verifiers
    assert all(verifier.family != drafter.family for verifier in verifiers)


def test_the_judge_is_from_neither_the_drafters_nor_the_verifiers_family() -> None:
    drafter = DRAFTING_MODELS[0]
    verifier = other_families(VERIFYING_MODELS, drafter.family)[0]
    assert JUDGING_MODELS[0].family not in {drafter.family, verifier.family}
