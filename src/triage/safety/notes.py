from collections.abc import Sequence

from triage.domain import Category, Language, Priority
from triage.safety.rules import RuleHit

GENERIC_NEXT_STEP = "Read the ticket and answer the customer yourself."
MAX_SUMMARY_CHARS = 300


def handoff_note(
    *,
    priority: Priority,
    category: Category,
    language: Language,
    plan: str,
    hits: Sequence[RuleHit] = (),
    reasons: Sequence[str] = (),
    summary: str | None = None,
) -> str:
    lines = [f"[{priority.value} · {category.value} · {language.value} · {plan or 'plan unknown'}]"]
    why = [f"{hit.rule.code} {hit.rule.summary}" for hit in hits]
    why += [reason.rstrip(" .") for reason in reasons]
    if why:
        lines.append(f"Why a human: {'; '.join(why)}.")
    if summary:
        lines.append(f"Customer says (unverified): {' '.join(summary.split())[:MAX_SUMMARY_CHARS]}")
    lines.append(f"Next step: {hits[0].rule.next_step if hits else GENERIC_NEXT_STEP}")
    return "\n".join(lines)
