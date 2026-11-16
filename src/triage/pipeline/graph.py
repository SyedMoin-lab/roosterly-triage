import asyncio
import operator
import secrets
from dataclasses import asdict
from typing import Annotated, Any, TypedDict, cast

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


class State(TypedDict, total=False):
    ticket: Ticket
    prepared: Prepared
    nonce: str
    injection_probability: float | None
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
    def __init__(self, gateway: ModelGateway, faq: Faq) -> None:
        self._gateway = gateway
        self._faq = faq
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
        return {"prepared": prepare(state["ticket"], self._faq), "nonce": secrets.token_hex(4)}

    def _after_prepare(self, state: State) -> str:
        prepared = state["prepared"]
        skip_models = prepared.is_empty or (prepared.is_automatic_reply and not prepared.hits)
        return "policy" if skip_models else "screen"

    async def _screen(self, state: State) -> dict[str, Any]:
        calls: list[CallRecord] = []
        probability = await self._gateway.injection_probability(state["prepared"].text, calls)
        return {"injection_probability": probability, "calls": calls}

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
                return {"triage": None, "calls": calls}
            raise
        return {"triage": answer.value, "triage_family": answer.spec.family, "calls": calls}

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
                self._gateway.structured("vote", TriageProposal, messages, (voter,), calls[index])
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
        audit = answers[-1].value
        return {
            "votes": votes,
            "audit": audit if isinstance(audit, SafetyAudit) else None,
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
        return {"route": route}

    def _after_policy(self, state: State) -> str:
        return "draft" if state["route"].action is Action.REPLY else "finalize"

    async def _draft(self, state: State) -> dict[str, Any]:
        calls: list[CallRecord] = []
        prepared, route = state["prepared"], state["route"]
        problems: list[str] = []
        draft: DraftReply | None = None
        family = ""
        for _ in range(DRAFT_ATTEMPTS):
            messages = draft_messages(prepared, route, self._faq, state["nonce"], problems)
            answer = await self._gateway.structured(
                "draft", DraftReply, messages, DRAFTING_MODELS, calls
            )
            draft, family = answer.value, answer.spec.family
            problems = self._draft_problems(draft, prepared, route)
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
        return {"verification": answer.value, "calls": calls}

    async def _finalize(self, state: State) -> dict[str, Any]:
        return {"decision": build_decision(state)}


class PipelineDecider:
    name = "pipeline"

    def __init__(self, pipeline: Pipeline, faq: Faq) -> None:
        self._pipeline = pipeline
        self._faq = faq

    async def decide(self, ticket: Ticket) -> Verdict:
        state = await self._pipeline.run(ticket)
        return Verdict(state["decision"], build_trace(state, self._faq))


def build_decision(state: State) -> Decision:
    route, prepared = state["route"], state["prepared"]
    triage = state.get("triage")
    if route.action is Action.REPLY:
        problem = _reply_problem(state)
        draft = state.get("draft")
        if problem is None and draft is not None:
            return Decision(
                action=Action.REPLY,
                language=route.language,
                category=route.category,
                priority=route.priority,
                reason=_clip(triage.reason if triage else "Answered from the help centre."),
                draft_reply=draft.reply,
                confidence=route.agreement,
            )
        route = route.escalated(*(problem or ("the reply could not be checked", "UNCHECKED")))
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


def _english_summary(triage: TriageProposal | None) -> str | None:
    if triage is None or detect_language(triage.english_summary) is not Language.ENGLISH:
        return None
    return redact(triage.english_summary).text


def _handoff_reason(prepared: Prepared, route: Route) -> str:
    if prepared.hits:
        summary = prepared.hits[0].rule.summary
        return _clip(f"{summary[0].upper()}{summary[1:]}: the client's rules send it to a human.")
    if route.reasons:
        return _clip(f"Handed to a human: {route.reasons[-1]}.")
    return "Handed to a human."


def _clip(text: str) -> str:
    clean = " ".join(redact(text).text.split())
    return clean if len(clean) <= MAX_REASON_CHARS else f"{clean[: MAX_REASON_CHARS - 3]}..."
