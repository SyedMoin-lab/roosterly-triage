from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from triage.domain import Action, Category, Decision, Language, Priority, Ticket, safe_ticket_id

BASE = {"language": "nl", "category": "question", "priority": "P4", "reason": "FAQ F02."}


def test_enum_values_match_the_api_reference() -> None:
    assert {language.value for language in Language} == {"nl", "en", "de"}
    assert {category.value for category in Category} == {
        "bug",
        "billing",
        "feature_request",
        "question",
        "other",
    }
    assert {priority.value for priority in Priority} == {"P1", "P2", "P3", "P4"}
    assert {action.value for action in Action} == {"reply", "handoff", "close"}


@pytest.mark.parametrize(
    ("action", "fields"),
    [("reply", {"draft_reply": "Hoi"}), ("handoff", {"handoff_note": "Refund."}), ("close", {})],
)
def test_each_action_accepts_its_own_fields(action: str, fields: dict[str, str]) -> None:
    decision = Decision.model_validate({"action": action, **BASE, **fields})
    assert decision.request_body() == {**BASE, **fields}


@pytest.mark.parametrize(
    ("action", "fields"),
    [
        ("reply", {}),
        ("reply", {"draft_reply": "Hoi", "handoff_note": "Note."}),
        ("handoff", {}),
        ("handoff", {"handoff_note": "Note.", "draft_reply": "Hoi"}),
        ("close", {"draft_reply": "Hoi"}),
        ("close", {"handoff_note": "Note."}),
    ],
)
def test_fields_that_do_not_fit_the_action_are_rejected(
    action: str, fields: dict[str, str]
) -> None:
    with pytest.raises(ValidationError, match="required for a"):
        Decision.model_validate({"action": action, **BASE, **fields})


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        Decision.model_validate({"action": "close", **BASE, "ticket_id": "T001"})


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_confidence_must_be_between_zero_and_one(confidence: float) -> None:
    with pytest.raises(ValidationError, match="confidence"):
        Decision.model_validate({"action": "close", **BASE, "confidence": confidence})


def test_a_blank_reason_is_rejected() -> None:
    with pytest.raises(ValidationError, match="reason"):
        Decision.model_validate({"action": "close", **BASE, "reason": "   "})


def test_the_request_body_leaves_out_the_action_and_unset_fields() -> None:
    body = Decision.model_validate({"action": "close", **BASE}).request_body()
    assert body == BASE


def test_missing_ticket_text_becomes_empty_strings() -> None:
    ticket = Ticket.model_validate(
        {"id": "T001", "received_at": "2026-10-05T06:12:00+00:00", "subject": None, "body": None}
    )
    assert (ticket.subject, ticket.body, ticket.channel) == ("", "", "")
    assert ticket.received_at == datetime(2026, 10, 5, 6, 12, tzinfo=UTC)


def test_unknown_ticket_fields_are_ignored() -> None:
    ticket = Ticket.model_validate(
        {"id": "T001", "received_at": "2026-10-05T06:12:00+00:00", "priority_hint": "P1"}
    )
    assert ticket.id == "T001"


@pytest.mark.parametrize("ticket_id", ["../x", "T001/close", "", "T 1", "T1;", "a" * 65])
def test_unsafe_ticket_ids_are_rejected(ticket_id: str) -> None:
    with pytest.raises(ValueError, match="unsafe ticket id"):
        safe_ticket_id(ticket_id)
