from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from triage.domain import Action, Category, Decision, Language, Priority, Ticket


class ProviderOutageError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Verdict:
    decision: Decision
    trace: Mapping[str, object] = field(default_factory=dict)


class Decider(Protocol):
    name: str

    async def decide(self, ticket: Ticket) -> Verdict: ...


class DrillDecider:
    name = "drill"

    async def decide(self, ticket: Ticket) -> Verdict:
        decision = Decision(
            action=Action.HANDOFF,
            language=Language.DUTCH,
            category=Category.OTHER,
            priority=Priority.P3,
            reason="Drill decision from the stub decider; no model was used.",
            handoff_note=(
                "Drill run: this ticket was not triaged automatically. Please triage it by hand."
            ),
        )
        return Verdict(decision, {"decider": self.name})
