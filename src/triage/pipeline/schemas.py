from typing import Literal

from pydantic import BaseModel, ConfigDict

from triage.domain import Action, Category, Language, Priority

NO_ENTRY = "none"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CustomerQuestion(_Strict):
    question: str
    faq_id: str


class TriageProposal(_Strict):
    language: Language
    category: Category
    priority: Priority
    action: Action
    questions: list[CustomerQuestion]
    evidence: list[str]
    english_summary: str
    reason: str

    def faq_ids(self) -> tuple[str, ...]:
        return tuple(sorted({q.faq_id for q in self.questions if q.faq_id != NO_ENTRY}))

    def every_question_has_an_entry(self, known: frozenset[str]) -> bool:
        return bool(self.questions) and all(q.faq_id in known for q in self.questions)


class SafetyAudit(_Strict):
    violation: bool
    rule: Literal["R1", "R2", "R3", "R4", "R5", "R6", "none"]
    rationale: str


class DraftReply(_Strict):
    reply: str
    cited_ids: list[str]
    evidence: list[str]


class Claim(_Strict):
    claim: str
    supported: bool


class Verification(_Strict):
    back_translation: str
    claims: list[Claim]
    answers_every_question: bool
    verdict: Literal["pass", "fail"]

    @property
    def passed(self) -> bool:
        return (
            self.verdict == "pass"
            and self.answers_every_question
            and all(claim.supported for claim in self.claims)
        )
