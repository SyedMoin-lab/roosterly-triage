import asyncio
import logging
import operator
import secrets
from collections.abc import Sequence
from dataclasses import asdict
from typing import Annotated, Any, Protocol, TypedDict, cast

import asyncpg
import httpx
import openai
from langgraph.graph import END, START, StateGraph

from triage.deciders import Verdict
from triage.domain import Action, Decision, Language, Ticket
from triage.knowledge.faq import Faq
from triage.language import detect_language
from triage.llm.gateway import AllModelsFailedError, CallRecord, ModelGateway
from triage.llm.roster import (
    AUDIT_MODELS,
    DRAFTING_MODELS,
    TRIAGE_MODELS,
    VERIFYING_MODELS,
    VOTING_MODELS,
    ModelSpec,
    other_families,
)
from triage.pipeline.policy import Route, decide_route, is_suspicious, needs_plus_caveat
from triage.pipeline.prepare import Prepared, prepare
from triage.pipeline.prompts import (
    PROMPT_VERSIONS,
    audit_messages,
    draft_messages,
    triage_messages,
    verify_messages,
)
from triage.pipeline.schemas import DraftReply, SafetyAudit, TriageProposal, Verification
from triage.safety.checks import check_draft
from triage.safety.notes import handoff_note
from triage.safety.redaction import redact, scrub

MAX_REASON_CHARS = 480
DRAFT_ATTEMPTS = 2
_RETRIEVAL_ERRORS = (openai.APIError, httpx.HTTPError, asyncpg.PostgresError, OSError)
_PLAIN_CODES = {
    "AUDIT": "the safety audit matched a client rule",
    "AUTO": "it is an automatic reply",
    "CHECKS": "the draft failed the code checks",
    "DISAGREE": "the second opinions disagree",
    "EMPTY": "the ticket is empty",
    "INJECTION": "the ticket contains instructions aimed at the agent",
    "MODEL": "the triage model wants a person to handle it",
    "P1": "it is urgent (P1)",
    "SPAM": "it is spam",
    "UNCHECKED": "the reply could not be checked",
    "UNCOVERED": "the help centre does not answer every question",
    "VERIFY": "the back-translation found claims the help centre does not support",
}

log = logging.getLogger(__name__)


class Retriever(Protocol):
    async def search(self, text: str, language: Language) -> list[str]: ...


class State(TypedDict, total=False):
    ticket: Ticket
    prepared: Prepared
    nonce: str
    injection_probability: float | None
    retrieval: list[str] | None
    triage: TriageProposal | None
    triage_family: str
    votes: list[TriageProposal]
    audit: SafetyAudit | None
    route: Route
    draft: DraftReply | None
    draft_family: str
    failures: list[str]
    verification: Verification | None
    decision: Decision
    calls: Annotated[list[CallRecord], operator.add]


class Pipeline:
    def __init__(self, gateway: ModelGateway, faq: Faq, retriever: Retriever | None = None) -> None:
        self._gateway = gateway
        self._faq = faq
        self._retriever = retriever
        graph = StateGraph(State)
        graph.add_node("prepare", self._prepare)
        graph.add_node("screen", self._screen)
        graph.add_node("triage", self._triage)
        graph.add_node("confirm", self._confirm)
        graph.add_node("policy", self._policy)
        graph.add_node("draft", self._draft)
        graph.add_node("verify", self._verify)
        graph.add_node("finalize", self._finalize)
        graph.add_edge(START, "prepare")
        graph.add_conditional_edges("prepare", self._after_prepare, ["screen", "policy"])
        graph.add_edge("screen", "triage")
        graph.add_conditional_edges("triage", self._after_triage, ["confirm", "policy"])
        graph.add_edge("confirm", "policy")
        graph.add_conditional_edges("policy", self._after_policy, ["draft", "finalize"])
        graph.add_conditional_edges("draft", self._after_draft, ["verify", "finalize"])
        graph.add_edge("verify", "finalize")
        graph.add_edge("finalize", END)
        self.graph = graph.compile()

    async def run(self, ticket: Ticket) -> State:
        return cast(State, await self.graph.ainvoke({"ticket": ticket, "calls": []}))

    async def _prepare(self, state: State) -> dict[str, Any]:
        prepared = prepare(state["ticket"], self._faq)
        log.info("read the ticket: %s", _describe_ticket(prepared))
        return {"prepared": prepared, "nonce": secrets.token_hex(4)}

    def _after_prepare(self, state: State) -> str:
        prepared = state["prepared"]
        return "policy" if prepared.is_empty else "screen"

    async def _screen(self, state: State) -> dict[str, Any]:
        calls: list[CallRecord] = []
        prepared = state["prepared"]
        probability, retrieval = await asyncio.gather(
            self._gateway.injection_probability(prepared.text, calls),
            self._retrieve(prepared),
        )
        log.info("injection check: %s", _describe_screen(prepared, probability))
        if retrieval is not None:
            log.info("FAQ vector search: closest entries %s", ", ".join(retrieval) or "none")
        return {"injection_probability": probability, "retrieval": retrieval, "calls": calls}

    async def _retrieve(self, prepared: Prepared) -> list[str] | None:
        if self._retriever is None:
            return None
        language = prepared.detected_language or Language.DUTCH
        try:
            return await self._retriever.search(prepared.text, language)
        except _RETRIEVAL_ERRORS:
            return None

    async def _triage(self, state: State) -> dict[str, Any]:
        calls: list[CallRecord] = []
        prepared = state["prepared"]
        messages = triage_messages(prepared, self._faq, state["nonce"])
        try:
            answer = await self._gateway.structured(
                "triage", TriageProposal, messages, TRIAGE_MODELS, calls
            )
        except AllModelsFailedError:
            if prepared.hits:
                log.info("triage: no model answered, so the client rules decide")
                return {"triage": None, "calls": calls}
            raise
        triage = answer.value
        log.info(
            "triage (%s): %s, %s, %s, proposes %s%s",
            answer.spec.short_name,
            triage.language.name.title(),
            triage.category,
            triage.priority,
            triage.action,
            _citing(triage.faq_ids()),
        )
        return {"triage": triage, "triage_family": answer.spec.family, "calls": calls}

    def _after_triage(self, state: State) -> str:
        triage = state.get("triage")
        prepared = state["prepared"]
        worth_confirming = (
            triage is not None
            and triage.action in {Action.REPLY, Action.CLOSE}
            and not prepared.hits
            and not is_suspicious(prepared, state.get("injection_probability"))
        )
        return "confirm" if worth_confirming else "policy"

    async def _confirm(self, state: State) -> dict[str, Any]:
        prepared = state["prepared"]
        voters = other_families(VOTING_MODELS, state["triage_family"])[:2]
        calls: list[list[CallRecord]] = [[] for _ in range(len(voters) + 1)]
        messages = triage_messages(prepared, self._faq, state["nonce"])
        outcomes = await asyncio.gather(
            *(
                self._gateway.structured(
                    "vote", TriageProposal, messages, _with_backup(voter, voters), calls[index]
                )
                for index, voter in enumerate(voters)
            ),
            self._gateway.structured(
                "audit",
                SafetyAudit,
                audit_messages(prepared, state["nonce"]),
                AUDIT_MODELS,
                calls[-1],
            ),
            return_exceptions=True,
        )
        failure = next((item for item in outcomes if isinstance(item, BaseException)), None)
        if failure is not None:
            raise failure
        answers = [item for item in outcomes if not isinstance(item, BaseException)]
        votes = [
            answer.value for answer in answers[:-1] if isinstance(answer.value, TriageProposal)
        ]
        audit = answers[-1].value if isinstance(answers[-1].value, SafetyAudit) else None
        opinions = ", ".join(
            f"{answer.spec.short_name} says {answer.value.action}"
            for answer in answers[:-1]
            if isinstance(answer.value, TriageProposal)
        )
        log.info(
            "second opinions: %s; rules audit (%s): %s",
            opinions or "none",
            answers[-1].spec.short_name,
            _describe_audit(audit),
        )
        return {
            "votes": votes,
            "audit": audit,
            "calls": [call for group in calls for call in group],
        }

    async def _policy(self, state: State) -> dict[str, Any]:
        route = decide_route(
            state["prepared"],
            state.get("triage"),
            state.get("votes", []),
            state.get("audit"),
            state.get("injection_probability"),
            self._faq,
        )
        log.info("decision rules: %s", _describe_route(route, state["prepared"]))
        return {"route": route}

    def _after_policy(self, state: State) -> str:
        return "draft" if state["route"].action is Action.REPLY else "finalize"

    async def _draft(self, state: State) -> dict[str, Any]:
        calls: list[CallRecord] = []
        prepared, route = state["prepared"], state["route"]
        problems: list[str] = []
        draft: DraftReply | None = None
        family = ""
        for attempt in range(1, DRAFT_ATTEMPTS + 1):
            messages = draft_messages(prepared, route, self._faq, state["nonce"], problems)
            answer = await self._gateway.structured(
                "draft", DraftReply, messages, DRAFTING_MODELS, calls
            )
            draft, family = answer.value, answer.spec.family
            problems = self._draft_problems(draft, prepared, route)
            log.info(
                "draft %d (%s): %s", attempt, answer.spec.short_name, _describe_problems(problems)
            )
            if not problems:
                break
        return {"draft": draft, "draft_family": family, "failures": problems, "calls": calls}

    def _draft_problems(self, draft: DraftReply, prepared: Prepared, route: Route) -> list[str]:
        failures = check_draft(
            draft.reply,
            faq=self._faq,
            cited_ids=draft.cited_ids,
            evidence=draft.evidence,
            covers_every_question=True,
            language=route.language,
            ticket_text=prepared.text,
        )
        problems = [f"{failure.code}: {failure.detail}" for failure in failures]
        outside = sorted(set(draft.cited_ids) - set(route.cited_ids))
        if outside:
            problems.append(f"G1: cites entries outside the agreed answer: {', '.join(outside)}")
        plan = prepared.ticket.customer_plan
        if needs_plus_caveat(route.cited_ids, plan) and "Plus" not in draft.reply:
            problems.append("PLAN: the reply must say that this needs the Plus plan")
        return problems

    def _after_draft(self, state: State) -> str:
        return "finalize" if state.get("failures") else "verify"

    async def _verify(self, state: State) -> dict[str, Any]:
        calls: list[CallRecord] = []
        draft, triage = state.get("draft"), state.get("triage")
        if draft is None or triage is None:
            return {"verification": None}
        verifiers = other_families(VERIFYING_MODELS, state["draft_family"])
        messages = verify_messages(draft.reply, triage, self._faq, state["route"], state["nonce"])
        answer = await self._gateway.structured("verify", Verification, messages, verifiers, calls)
        log.info(
            "back-translation check (%s): %s",
            answer.spec.short_name,
            _describe_verification(answer.value),
        )
        return {"verification": answer.value, "calls": calls}

    async def _finalize(self, state: State) -> dict[str, Any]:
        route = settle_route(state)
        if route is not state["route"]:
            log.info("after the checks: %s", _describe_route(route, state["prepared"]))
        return {"route": route, "decision": build_decision(state, route)}


class PipelineDecider:
    name = "pipeline"

    def __init__(self, pipeline: Pipeline, faq: Faq) -> None:
        self._pipeline = pipeline
        self._faq = faq

    async def decide(self, ticket: Ticket) -> Verdict:
        state = await self._pipeline.run(ticket)
        return Verdict(state["decision"], build_trace(state, self._faq))


def _with_backup(voter: ModelSpec, voters: tuple[ModelSpec, ...]) -> tuple[ModelSpec, ...]:
    return (voter, *(spec for spec in voters if spec is not voter))


def settle_route(state: State) -> Route:
    route = state["route"]
    if route.action is not Action.REPLY:
        return route
    problem = _reply_problem(state)
    if problem is None and state.get("draft") is not None:
        return route
    return route.escalated(*(problem or ("the reply could not be checked", "UNCHECKED")))


def build_decision(state: State, route: Route) -> Decision:
    prepared, triage = state["prepared"], state.get("triage")
    if route.action is Action.REPLY and (draft := state.get("draft")) is not None:
        return Decision(
            action=Action.REPLY,
            language=route.language,
            category=route.category,
            priority=route.priority,
            reason=_clip(triage.reason if triage else "Answered from the help centre."),
            draft_reply=draft.reply,
            confidence=route.agreement,
        )
    if route.action is Action.CLOSE:
        return Decision(
            action=Action.CLOSE,
            language=route.language,
            category=route.category,
            priority=route.priority,
            reason=f"Closed: {route.reasons[0] if route.reasons else 'nothing to answer'}.",
            confidence=route.agreement,
        )
    note = handoff_note(
        priority=route.priority,
        category=route.category,
        language=route.language,
        plan=prepared.ticket.customer_plan,
        hits=prepared.hits,
        reasons=route.reasons,
        summary=_english_summary(triage),
    )
    return Decision(
        action=Action.HANDOFF,
        language=route.language,
        category=route.category,
        priority=route.priority,
        reason=_handoff_reason(prepared, route),
        handoff_note=redact(note).text,
        confidence=route.agreement,
    )


def build_trace(state: State, faq: Faq) -> dict[str, object]:
    route, prepared = state["route"], state["prepared"]
    triage, audit = state.get("triage"), state.get("audit")
    verification = state.get("verification")
    calls = state.get("calls", [])
    raw: dict[str, object] = {
        "decider": "pipeline",
        "codes": list(route.codes),
        "faq_sha": faq.sha256[:12],
        "prompts": PROMPT_VERSIONS,
        "flags": sorted(prepared.flags),
        "redacted": prepared.redacted,
        "detected_language": prepared.detected_language,
        "injection_probability": state.get("injection_probability"),
        "retrieval": state.get("retrieval"),
        "retrieval_agrees": _retrieval_agrees(state.get("retrieval"), triage),
        "triage": triage.model_dump(mode="json") if triage else None,
        "votes": [f"{vote.action}:{','.join(vote.faq_ids())}" for vote in state.get("votes", [])],
        "audit": audit.model_dump(mode="json") if audit else None,
        "draft_failures": state.get("failures", []),
        "verification": verification.model_dump(mode="json") if verification else None,
        "calls": [asdict(call) for call in calls],
        "tokens": sum(call.input_tokens + call.output_tokens for call in calls),
        "cost_usd": round(sum(call.cost_usd for call in calls), 6),
    }
    return {key: scrub(value) for key, value in raw.items()}


def _reply_problem(state: State) -> tuple[str, str] | None:
    failures = state.get("failures", [])
    if failures:
        codes = sorted({failure.split(":", 1)[0] for failure in failures})
        return f"the draft failed checks {', '.join(codes)}", "CHECKS"
    verification = state.get("verification")
    if verification is None or not verification.passed:
        return "the verifier found claims the help centre does not support", "VERIFY"
    return None


def _retrieval_agrees(retrieval: list[str] | None, triage: TriageProposal | None) -> bool | None:
    if retrieval is None or triage is None or not triage.faq_ids():
        return None
    return bool(set(retrieval) & set(triage.faq_ids()))


def _english_summary(triage: TriageProposal | None) -> str | None:
    if triage is None or detect_language(triage.english_summary) is not Language.ENGLISH:
        return None
    return redact(triage.english_summary).text


def _handoff_reason(prepared: Prepared, route: Route) -> str:
    if prepared.hits:
        summary = prepared.hits[0].rule.summary
        return _clip(f"{summary[0].upper()}{summary[1:]}: the client's rules send it to a human.")
    if route.reasons:
        return _clip(f"Handed to a human: {route.reasons[-1].rstrip(' .')}.")
    return "Handed to a human."


def _clip(text: str) -> str:
    clean = " ".join(redact(text).text.split())
    return clean if len(clean) <= MAX_REASON_CHARS else f"{clean[: MAX_REASON_CHARS - 3]}..."


def _describe_ticket(prepared: Prepared) -> str:
    language = prepared.detected_language
    parts = [
        language.name.title() if language else "language unclear",
        f"{len(prepared.text)} characters",
    ]
    if prepared.is_empty:
        parts.append("empty")
    if prepared.is_automatic_reply:
        parts.append("looks like an automatic reply")
    parts += [f"client rule {hit.rule.code} ({hit.rule.summary})" for hit in prepared.hits]
    if prepared.redacted:
        hidden = ", ".join(f"{n} {kind.upper()}" for kind, n in sorted(prepared.redacted.items()))
        parts.append(f"hid {hidden}")
    return ", ".join(parts)


def _describe_screen(prepared: Prepared, probability: float | None) -> str:
    score = (
        "no Prompt Guard score (model unavailable)"
        if probability is None
        else f"Prompt Guard score {probability:.2f}"
    )
    pattern = "an injection pattern matched" if prepared.injection else "no injection patterns"
    return f"{score}, {pattern}"


def _citing(ids: Sequence[str]) -> str:
    return f", cites {', '.join(ids)}" if ids else ""


def _describe_audit(audit: SafetyAudit | None) -> str:
    if audit is None:
        return "no answer"
    return f"matches client rule {audit.rule}" if audit.violation else "clean"


def _describe_route(route: Route, prepared: Prepared) -> str:
    if not route.codes:
        return str(route.action)
    rules = {hit.rule.code: hit.rule.summary for hit in prepared.hits}
    why = "; ".join(
        f"client rule {code} ({rules[code]})" if code in rules else _PLAIN_CODES.get(code, code)
        for code in route.codes
    )
    return f"{route.action}, because {why}"


def _describe_problems(problems: Sequence[str]) -> str:
    if not problems:
        return "passes the code checks"
    return "fails " + ", ".join(sorted({problem.split(":", 1)[0] for problem in problems}))


def _describe_verification(verification: Verification) -> str:
    if verification.passed:
        return "passed, every claim is in the help centre"
    unsupported = sum(not claim.supported for claim in verification.claims)
    if unsupported:
        total = len(verification.claims)
        return f"failed, {unsupported} of {total} claims are not in the help centre"
    if not verification.answers_every_question:
        return "failed, not every question is answered"
    return "failed"
