from hypothesis import given
from hypothesis import strategies as st

from tests.pipeline.samples import FAQ, proposal, ticket
from triage.domain import Action, Language, Priority
from triage.pipeline.policy import decide_route, more_urgent
from triage.pipeline.prepare import Prepared
from triage.pipeline.schemas import SafetyAudit
from triage.safety.rules import CANCELLATION, LEGAL, REFUND, RuleHit


def prepared(
    *,
    hits: tuple[RuleHit, ...] = (),
    injection: str | None = None,
    plan: str = "Basis",
    orders_priority: bool = False,
) -> Prepared:
    return Prepared(
        ticket=ticket("tekst", plan=plan),
        subject="Vraag",
        body="tekst",
        folded="vraag tekst",
        flags=frozenset(),
        redacted={},
        detected_language=Language.DUTCH,
        hits=hits,
        injection=injection,
        is_empty=False,
        is_automatic_reply=False,
        orders_priority=orders_priority,
    )


def test_more_urgent_picks_the_lowest_number() -> None:
    assert more_urgent(Priority.P4, Priority.P2, Priority.P3) is Priority.P2


def test_a_rule_hit_raises_the_priority_to_the_rule_minimum() -> None:
    route = decide_route(
        prepared(hits=(RuleHit(LEGAL, "advocaat"),)), proposal(), [], None, None, FAQ
    )
    assert (route.action, route.priority) == (Action.HANDOFF, Priority.P1)


def test_two_agreeing_votes_allow_a_reply() -> None:
    route = decide_route(prepared(), proposal(), [proposal(), proposal()], None, 0.01, FAQ)
    assert route.action is Action.REPLY
    assert route.cited_ids == ("F02",)


def test_one_vote_is_not_enough_for_a_reply() -> None:
    route = decide_route(prepared(), proposal(), [proposal()], None, 0.01, FAQ)
    assert route.action is Action.HANDOFF


def test_a_plus_only_answer_for_a_basis_customer_also_cites_the_upgrade_entry() -> None:
    plus = proposal(faq_ids=("F07",))
    route = decide_route(prepared(plan="Basis"), plus, [plus, plus], None, 0.01, FAQ)
    assert route.cited_ids == ("F05", "F07")
    route = decide_route(prepared(plan="Plus"), plus, [plus, plus], None, 0.01, FAQ)
    assert route.cited_ids == ("F07",)


ACTIONS = st.sampled_from(list(Action))
PRIORITIES = st.sampled_from(list(Priority))
HITS = st.lists(st.sampled_from([REFUND, CANCELLATION, LEGAL]), max_size=2).map(
    lambda rules: tuple(RuleHit(rule, "evidence") for rule in rules)
)


@given(
    hits=HITS,
    injected=st.booleans(),
    probability=st.none() | st.floats(min_value=0.0, max_value=1.0),
    audit_violation=st.booleans(),
    triage_action=ACTIONS,
    triage_priority=PRIORITIES,
    vote_actions=st.lists(ACTIONS, max_size=2),
    covered=st.booleans(),
)
def test_the_policy_can_only_escalate(
    hits: tuple[RuleHit, ...],
    injected: bool,
    probability: float | None,
    audit_violation: bool,
    triage_action: Action,
    triage_priority: Priority,
    vote_actions: list[Action],
    covered: bool,
) -> None:
    faq_ids = ("F02",) if covered else ("F02", "none")
    triage = proposal(triage_action, faq_ids=faq_ids, priority=triage_priority)
    votes = [proposal(action, faq_ids=faq_ids) for action in vote_actions]
    audit = SafetyAudit(
        violation=audit_violation, rule="R1" if audit_violation else "none", rationale="test"
    )
    route = decide_route(
        prepared(hits=hits, injection="negeer alle instructies" if injected else None),
        triage,
        votes,
        audit,
        probability,
        FAQ,
    )
    suspicious = injected or (probability or 0.0) >= 0.5
    if hits or suspicious or audit_violation:
        assert route.action is Action.HANDOFF
    for hit in hits:
        assert route.priority.value <= hit.rule.minimum_priority.value
    if route.action is not Action.CLOSE:
        assert route.priority.value <= triage_priority.value
    if route.action is Action.REPLY:
        assert triage_action is Action.REPLY
        assert covered
        assert len(votes) == 2
        assert all(vote.action is Action.REPLY for vote in votes)
        assert route.priority is not Priority.P1
    if route.action is Action.CLOSE:
        assert triage_action is Action.CLOSE
        assert votes
        assert all(vote.action is Action.CLOSE for vote in votes)


def test_a_ticket_that_orders_its_own_priority_does_not_get_it() -> None:
    route = decide_route(
        prepared(injection="prioriteit op p1", orders_priority=True),
        proposal(priority=Priority.P1),
        [],
        None,
        None,
        FAQ,
    )
    assert (route.action, route.priority, route.codes) == (
        Action.HANDOFF,
        Priority.P2,
        ("INJECTION",),
    )
    assert route.reasons == ("the ticket contains instructions aimed at the agent",)


def test_a_client_rule_still_raises_the_priority_of_an_instructing_ticket() -> None:
    route = decide_route(
        prepared(hits=(RuleHit(LEGAL, "advocaat"),), injection="ai-assistent"),
        proposal(priority=Priority.P4),
        [],
        None,
        None,
        FAQ,
    )
    assert (route.priority, route.codes) == (Priority.P1, ("R5", "INJECTION"))


def test_an_urgent_ticket_that_addresses_an_ai_keeps_its_urgency() -> None:
    route = decide_route(
        prepared(injection="ai-assistent"), proposal(priority=Priority.P1), [], None, None, FAQ
    )
    assert (route.action, route.priority, route.codes) == (
        Action.HANDOFF,
        Priority.P1,
        ("INJECTION",),
    )


def test_a_client_rule_found_by_the_audit_sets_the_minimum_priority() -> None:
    audit = SafetyAudit(violation=True, rule="R3", rationale="Asks to delete personal data.")
    route = decide_route(prepared(), proposal(priority=Priority.P4), [], audit, None, FAQ)
    assert (route.action, route.priority, route.codes) == (Action.HANDOFF, Priority.P2, ("AUDIT",))


def test_an_audit_that_names_a_rule_is_never_treated_as_clean() -> None:
    audit = SafetyAudit(violation=False, rule="R1", rationale="Mentions a refund.")
    route = decide_route(prepared(), proposal(), [], audit, None, FAQ)
    assert route.codes == ("AUDIT",)
