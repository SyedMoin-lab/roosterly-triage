from triage.domain import Category, Language, Priority
from triage.safety.notes import GENERIC_NEXT_STEP, handoff_note
from triage.safety.rules import REFUND, RuleHit


def test_a_rule_note_has_a_header_the_reason_and_the_rules_next_step() -> None:
    note = handoff_note(
        priority=Priority.P2,
        category=Category.BILLING,
        language=Language.DUTCH,
        plan="Basis",
        hits=[RuleHit(REFUND, "terugkrijgen")],
        summary="Customer asks to get August back because the shop was closed.",
    )
    assert note.splitlines() == [
        "[P2 · billing · nl · Basis]",
        "Why a human: R1 refund or disputed charge.",
        "Customer says (unverified): Customer asks to get August back because the shop was closed.",
        f"Next step: {REFUND.next_step}",
    ]


def test_a_note_without_rules_uses_the_generic_next_step_and_a_plan_placeholder() -> None:
    note = handoff_note(
        priority=Priority.P3,
        category=Category.QUESTION,
        language=Language.ENGLISH,
        plan="",
        reasons=["no FAQ entry covers the question"],
    )
    assert note.startswith("[P3 · question · en · plan unknown]")
    assert "Why a human: no FAQ entry covers the question." in note
    assert note.endswith(f"Next step: {GENERIC_NEXT_STEP}")


def test_a_long_summary_is_shortened() -> None:
    note = handoff_note(
        priority=Priority.P4,
        category=Category.OTHER,
        language=Language.DUTCH,
        plan="Plus",
        summary="word " * 200,
    )
    summary_line = next(line for line in note.splitlines() if line.startswith("Customer says"))
    assert len(summary_line) < 340
