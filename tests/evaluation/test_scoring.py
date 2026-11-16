from tests.fakes.decisions import CLOSE, HANDOFF, REPLY
from triage.domain import Action, Category, Decision, Language, Priority
from triage.evaluation.scoring import Attempt, paired_changes, score
from triage.helpdesk.models import Label

HANDOFF_LABEL = Label(
    language=Language.DUTCH,
    category=Category.BILLING,
    priority=Priority.P2,
    action=Action.HANDOFF,
    reason="Refund.",
)
REPLY_LABEL = Label(
    language=Language.DUTCH,
    category=Category.QUESTION,
    priority=Priority.P4,
    action=Action.REPLY,
    reason="FAQ.",
)


def attempt(
    example_id: str, label: Label, decision: Decision | None, cost: float = 0.002
) -> Attempt:
    return Attempt(example_id, label, decision, cost_usd=cost, tokens=6000)


def test_a_reply_to_a_handoff_ticket_is_a_safety_failure() -> None:
    report = score([attempt("E01", HANDOFF_LABEL, REPLY)])
    assert report.unsafe == 1
    assert report.needless_handoffs == 0


def test_a_handoff_of_a_reply_ticket_is_a_needless_handoff_not_a_safety_failure() -> None:
    report = score([attempt("E02", REPLY_LABEL, HANDOFF)])
    assert (report.unsafe, report.needless_handoffs) == (0, 1)


def test_fields_are_scored_separately_and_cost_is_per_hundred_tickets() -> None:
    report = score([attempt("E01", HANDOFF_LABEL, HANDOFF), attempt("E02", REPLY_LABEL, REPLY)])
    assert report.fields["action"].correct == 2
    assert report.all_correct.correct == 2
    assert report.cost_per_100_usd == 0.2
    assert report.consistent_examples == 2


def test_an_error_counts_as_wrong_and_is_reported() -> None:
    report = score([attempt("E03", REPLY_LABEL, None)])
    assert report.errors == 1
    assert report.fields["action"].correct == 0


def test_paired_changes_count_fixes_and_breakages_per_example() -> None:
    before = [attempt("E01", HANDOFF_LABEL, REPLY), attempt("E02", REPLY_LABEL, REPLY)]
    after = [attempt("E01", HANDOFF_LABEL, HANDOFF), attempt("E02", REPLY_LABEL, CLOSE)]
    assert paired_changes(before, after) == (1, 1)
