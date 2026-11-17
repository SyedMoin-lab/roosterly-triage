from collections.abc import Sequence
from dataclasses import dataclass, replace

from triage.domain import Action, Category, Language, Priority
from triage.knowledge.faq import Faq
from triage.pipeline.prepare import Prepared
from triage.pipeline.schemas import NO_ENTRY, SafetyAudit, TriageProposal

INJECTION_THRESHOLD = 0.5
# Ticket text is data: a ticket that gives the agent instructions cannot set its own priority.
# The triage model has read those instructions, so the code sets it (or a client rule's floor).
INJECTION_PRIORITY = Priority.P2
INJECTION_REASON = "the ticket contains instructions aimed at the agent"
PLUS_ONLY_ENTRIES = frozenset({"F04", "F07"})
UPGRADE_ENTRY = "F05"
_RULE_CATEGORIES = {"R1": Category.BILLING, "R2": Category.BILLING}


@dataclass(frozen=True, slots=True)
class Route:
    action: Action
    language: Language
    category: Category
    priority: Priority
    cited_ids: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    codes: tuple[str, ...] = ()
    agreement: float = 1.0

    def escalated(self, reason: str, code: str) -> "Route":
        return replace(
            self,
            action=Action.HANDOFF,
            cited_ids=(),
            reasons=(*self.reasons, reason),
            codes=(*self.codes, code),
        )


def more_urgent(*priorities: Priority) -> Priority:
    return min(priorities, key=lambda priority: priority.value)


def needs_plus_caveat(cited_ids: Sequence[str], plan: str) -> bool:
    return plan != "Plus" and bool(PLUS_ONLY_ENTRIES.intersection(cited_ids))


def is_suspicious(prepared: Prepared, injection_probability: float | None) -> bool:
    return prepared.injection is not None or (injection_probability or 0.0) >= INJECTION_THRESHOLD


def decide_route(
    prepared: Prepared,
    triage: TriageProposal | None,
    votes: Sequence[TriageProposal],
    audit: SafetyAudit | None,
    injection_probability: float | None,
    faq: Faq,
) -> Route:
    rule_codes = tuple(hit.rule.code for hit in prepared.hits)
    rule_floor = [hit.rule.minimum_priority for hit in prepared.hits]
    if triage is None:
        return _without_a_model(prepared, rule_codes, rule_floor)
    language = prepared.detected_language or triage.language
    suspicious = is_suspicious(prepared, injection_probability)
    base = Route(
        Action.HANDOFF,
        language,
        triage.category,
        more_urgent(INJECTION_PRIORITY if suspicious else triage.priority, *rule_floor),
        codes=rule_codes,
    )
    if suspicious:
        return base.escalated(INJECTION_REASON, "INJECTION")
    if prepared.hits:
        return base
    if audit is not None and audit.violation:
        return base.escalated(f"the safety audit matched client rule {audit.rule}", "AUDIT")
    if prepared.is_automatic_reply:
        return replace(base, action=Action.CLOSE, reasons=("an automatic reply",), codes=("AUTO",))
    if triage.action is Action.CLOSE:
        return _close_if_unanimous(base, votes)
    if triage.action is Action.REPLY:
        return _reply_if_confirmed(base, triage, votes, faq, prepared.ticket.customer_plan)
    return base.escalated(triage.reason, "MODEL")


def _without_a_model(
    prepared: Prepared, rule_codes: tuple[str, ...], rule_floor: list[Priority]
) -> Route:
    language = prepared.detected_language or Language.DUTCH
    if prepared.hits:
        category = _RULE_CATEGORIES.get(rule_codes[0], Category.OTHER)
        return Route(Action.HANDOFF, language, category, more_urgent(*rule_floor), codes=rule_codes)
    if prepared.is_empty:
        return Route(
            Action.CLOSE,
            language,
            Category.OTHER,
            Priority.P4,
            (),
            ("an empty ticket",),
            ("EMPTY",),
        )
    return Route(
        Action.CLOSE, language, Category.OTHER, Priority.P4, (), ("an automatic reply",), ("AUTO",)
    )


def _close_if_unanimous(base: Route, votes: Sequence[TriageProposal]) -> Route:
    if votes and all(vote.action is Action.CLOSE for vote in votes):
        return replace(
            base,
            action=Action.CLOSE,
            category=Category.OTHER,
            priority=Priority.P4,
            reasons=("spam",),
            codes=("SPAM",),
        )
    return base.escalated("the models disagree about closing it", "DISAGREE")


def _reply_if_confirmed(
    base: Route, triage: TriageProposal, votes: Sequence[TriageProposal], faq: Faq, plan: str
) -> Route:
    cited = triage.faq_ids()
    if not triage.every_question_has_an_entry(faq.ids):
        return base.escalated("a question the help centre does not answer", "UNCOVERED")
    if base.priority is Priority.P1:
        return base.escalated("it is urgent (P1)", "P1")
    agreeing = [vote for vote in votes if _agrees(vote, cited, faq)]
    if len(votes) < 2 or len(agreeing) < len(votes):
        disagreement = base.escalated("the models disagree about the answer", "DISAGREE")
        return replace(disagreement, agreement=round((1 + len(agreeing)) / (1 + len(votes)), 2))
    return replace(base, action=Action.REPLY, cited_ids=_with_upgrade_entry(cited, plan))


def _agrees(vote: TriageProposal, cited: tuple[str, ...], faq: Faq) -> bool:
    return (
        vote.action is Action.REPLY
        and vote.every_question_has_an_entry(faq.ids)
        and bool(set(vote.faq_ids()) & set(cited))
        and NO_ENTRY not in {question.faq_id for question in vote.questions}
    )


def _with_upgrade_entry(cited: tuple[str, ...], plan: str) -> tuple[str, ...]:
    if needs_plus_caveat(cited, plan) and UPGRADE_ENTRY not in cited:
        return tuple(sorted((*cited, UPGRADE_ENTRY)))
    return cited
