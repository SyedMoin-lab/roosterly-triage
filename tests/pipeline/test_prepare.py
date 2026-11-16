from tests.pipeline.samples import FAQ, QUESTION, REFUND, ticket
from triage.domain import Language
from triage.pipeline.prepare import prepare


def test_a_plain_question_has_no_rules_and_is_detected_as_dutch() -> None:
    prepared = prepare(ticket(QUESTION), FAQ)
    assert prepared.hits == ()
    assert prepared.injection is None
    assert prepared.detected_language is Language.DUTCH
    assert not prepared.is_empty


def test_payment_details_are_redacted_before_anything_else_sees_them() -> None:
    prepared = prepare(ticket("Mijn IBAN is NL91ABNA0417164300, graag terugstorten."), FAQ)
    assert "NL91" not in prepared.text
    assert "[IBAN]" in prepared.body
    assert prepared.redacted == {"iban": 1}
    assert [hit.rule.code for hit in prepared.hits] == ["R1"]


def test_the_refund_rule_fires_on_the_folded_text() -> None:
    assert [hit.rule.code for hit in prepare(ticket(REFUND), FAQ).hits] == ["R1"]


def test_an_empty_ticket_and_an_automatic_reply_are_recognised() -> None:
    assert prepare(ticket("   ", subject=""), FAQ).is_empty
    auto = prepare(ticket("Ik ben momenteel afwezig. Automatisch antwoord.", subject="Re"), FAQ)
    assert auto.is_automatic_reply
