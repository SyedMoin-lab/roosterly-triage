from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from triage.domain import Action, Decision
from triage.evaluation.stats import wilson_interval
from triage.helpdesk.models import Label

FIELDS = ("action", "category", "priority", "language")


@dataclass(frozen=True, slots=True)
class Attempt:
    example_id: str
    label: Label
    decision: Decision | None
    cost_usd: float
    tokens: int
    codes: tuple[str, ...] = ()
    judged_good_reply: bool | None = None
    error: str | None = None
    models: tuple[str, ...] = ()
    failed_calls: int = 0

    def matches(self, name: str) -> bool:
        return self.decision is not None and getattr(self.decision, name) == getattr(
            self.label, name
        )

    @property
    def unsafe(self) -> bool:
        return (
            self.decision is not None
            and self.label.action is Action.HANDOFF
            and self.decision.action is not Action.HANDOFF
        )

    @property
    def needless_handoff(self) -> bool:
        return (
            self.decision is not None
            and self.label.action is not Action.HANDOFF
            and self.decision.action is Action.HANDOFF
        )

    @property
    def correct(self) -> bool:
        return all(self.matches(name) for name in FIELDS)


@dataclass(frozen=True, slots=True)
class FieldScore:
    correct: int
    total: int

    @property
    def share(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def interval(self) -> tuple[float, float]:
        return wilson_interval(self.correct, self.total)


@dataclass(frozen=True, slots=True)
class Report:
    attempts: tuple[Attempt, ...]
    fields: dict[str, FieldScore]
    unsafe: int
    needless_handoffs: int
    errors: int
    all_correct: FieldScore
    consistent_examples: int
    examples: int
    cost_per_100_usd: float
    tokens_per_ticket: float
    good_replies: FieldScore | None
    confusion: Counter[tuple[str, str]] = field(default_factory=Counter)


def score(attempts: Sequence[Attempt]) -> Report:
    decided = [attempt for attempt in attempts if attempt.decision is not None]
    by_example: dict[str, list[Attempt]] = {}
    for attempt in attempts:
        by_example.setdefault(attempt.example_id, []).append(attempt)
    judged = [attempt for attempt in attempts if attempt.judged_good_reply is not None]
    return Report(
        attempts=tuple(attempts),
        fields={
            name: FieldScore(sum(attempt.matches(name) for attempt in attempts), len(attempts))
            for name in FIELDS
        },
        unsafe=sum(attempt.unsafe for attempt in attempts),
        needless_handoffs=sum(attempt.needless_handoff for attempt in attempts),
        errors=sum(attempt.decision is None for attempt in attempts),
        all_correct=FieldScore(sum(attempt.correct for attempt in attempts), len(attempts)),
        consistent_examples=sum(
            all(attempt.correct for attempt in runs) for runs in by_example.values()
        ),
        examples=len(by_example),
        cost_per_100_usd=100 * sum(a.cost_usd for a in decided) / len(decided) if decided else 0.0,
        tokens_per_ticket=sum(a.tokens for a in decided) / len(decided) if decided else 0.0,
        good_replies=(
            FieldScore(sum(bool(a.judged_good_reply) for a in judged), len(judged))
            if judged
            else None
        ),
        confusion=Counter(
            (attempt.label.action.value, decision.action.value)
            for attempt in attempts
            if (decision := attempt.decision) is not None
        ),
    )


def majority_correct(attempts: Sequence[Attempt]) -> dict[str, bool]:
    votes: dict[str, list[bool]] = {}
    for attempt in attempts:
        votes.setdefault(attempt.example_id, []).append(attempt.correct)
    return {example: sum(runs) * 2 > len(runs) for example, runs in votes.items()}


def paired_changes(before: Sequence[Attempt], after: Sequence[Attempt]) -> tuple[int, int]:
    first, second = majority_correct(before), majority_correct(after)
    shared = first.keys() & second.keys()
    fixed = sum(not first[key] and second[key] for key in shared)
    broken = sum(first[key] and not second[key] for key in shared)
    return fixed, broken
