from hypothesis import given
from hypothesis import strategies as st

from tests.fakes.helpdesk import validation_problems
from triage.domain import Action, Category, Decision, Language, Priority


@given(
    action=st.sampled_from(Action),
    language=st.sampled_from(Language),
    category=st.sampled_from(Category),
    priority=st.sampled_from(Priority),
    reason=st.text(min_size=1, max_size=200).filter(str.strip),
    text=st.text(min_size=1, max_size=300).filter(str.strip),
    confidence=st.none() | st.floats(min_value=0.0, max_value=1.0),
)
def test_every_valid_decision_serialises_to_a_body_the_helpdesk_accepts(
    action: Action,
    language: Language,
    category: Category,
    priority: Priority,
    reason: str,
    text: str,
    confidence: float | None,
) -> None:
    decision = Decision(
        action=action,
        language=language,
        category=category,
        priority=priority,
        reason=reason,
        draft_reply=text if action is Action.REPLY else None,
        handoff_note=text if action is Action.HANDOFF else None,
        confidence=confidence,
    )
    assert validation_problems(action.value, decision.request_body()) == []
