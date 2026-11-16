import asyncio
import json
from collections.abc import Sequence
from pathlib import Path

from triage.deciders import Decider, ProviderOutageError
from triage.domain import Action
from triage.evaluation.judge import Judge
from triage.evaluation.scoring import FIELDS, Attempt, Report, majority_correct
from triage.evaluation.stats import mcnemar_exact
from triage.helpdesk.models import LabelledExample


async def evaluate(
    decider: Decider,
    examples: Sequence[LabelledExample],
    *,
    repeats: int,
    judge: Judge | None,
    concurrency: int = 2,
) -> list[Attempt]:
    semaphore = asyncio.Semaphore(concurrency)

    async def attempt(example: LabelledExample) -> Attempt:
        async with semaphore:
            try:
                verdict = await decider.decide(example)
            except ProviderOutageError as error:
                return Attempt(example.id, example.label, None, 0.0, 0, error=str(error))
            decision, trace = verdict.decision, verdict.trace
            judged = None
            if judge is not None and decision.action is Action.REPLY:
                judged = await judge.good_reply(example, decision)
            return Attempt(
                example.id,
                example.label,
                decision,
                cost_usd=_number(trace.get("cost_usd")),
                tokens=int(_number(trace.get("tokens"))),
                codes=tuple(str(code) for code in _sequence(trace.get("codes"))),
                judged_good_reply=judged,
            )

    return list(
        await asyncio.gather(*(attempt(example) for _ in range(repeats) for example in examples))
    )


def write_results(path: Path, report: Report, *, title: str, notes: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "example": attempt.example_id,
            "label": attempt.label.model_dump(mode="json", exclude={"reason"}),
            "decision": attempt.decision.model_dump(mode="json") if attempt.decision else None,
            "codes": list(attempt.codes),
            "judged_good_reply": attempt.judged_good_reply,
            "cost_usd": attempt.cost_usd,
            "tokens": attempt.tokens,
            "error": attempt.error,
        }
        for attempt in report.attempts
    ]
    payload = {
        "title": title,
        **notes,
        "summary": summary(report),
        "per_example": majority_correct(report.attempts),
        "attempts": rows,
    }
    path.with_suffix(".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    path.with_suffix(".md").write_text(render(report, title=title, notes=notes), encoding="utf-8")


def summary(report: Report) -> dict[str, object]:
    return {
        **{name: f"{field.correct}/{field.total}" for name, field in report.fields.items()},
        "all_fields_correct": f"{report.all_correct.correct}/{report.all_correct.total}",
        "unsafe": report.unsafe,
        "needless_handoffs": report.needless_handoffs,
        "errors": report.errors,
        "consistent_examples": f"{report.consistent_examples}/{report.examples}",
        "good_replies": (
            f"{report.good_replies.correct}/{report.good_replies.total}"
            if report.good_replies
            else None
        ),
        "cost_per_100_tickets_usd": round(report.cost_per_100_usd, 4),
        "tokens_per_ticket": round(report.tokens_per_ticket),
    }


def render(report: Report, *, title: str, notes: dict[str, object]) -> str:
    lines = [f"# {title}", ""]
    lines += [f"- {key}: {value}" for key, value in notes.items()]
    lines += ["", "| Measure | Result | 95% Wilson interval |", "|---|---|---|"]
    for name in (*FIELDS, "all fields"):
        field = report.all_correct if name == "all fields" else report.fields[name]
        low, high = field.interval
        lines.append(
            f"| {name} | {field.correct}/{field.total} ({field.share:.0%}) | "
            f"{low:.0%} to {high:.0%} |"
        )
    lines += [
        f"| unsafe (reply or close on a handoff ticket) | {report.unsafe} | |",
        f"| needless handoffs | {report.needless_handoffs} | |",
        f"| runs that failed (provider outage) | {report.errors} | |",
        f"| examples right on every run (pass^k) | {report.consistent_examples}/"
        f"{report.examples} | |",
    ]
    if report.good_replies:
        low, high = report.good_replies.interval
        lines.append(
            f"| replies the judge passed | {report.good_replies.correct}/"
            f"{report.good_replies.total} | {low:.0%} to {high:.0%} |"
        )
    lines += [
        f"| list-price cost per 100 tickets | ${report.cost_per_100_usd:.3f} | |",
        f"| tokens per ticket | {report.tokens_per_ticket:.0f} | |",
        "",
        "| Example | Label | Decisions | Majority correct |",
        "|---|---|---|---|",
    ]
    majority = majority_correct(report.attempts)
    for example in sorted(majority):
        runs = [attempt for attempt in report.attempts if attempt.example_id == example]
        label = runs[0].label
        decided = ", ".join(_describe(attempt) for attempt in runs)
        lines.append(
            f"| {example} | {label.action} {label.category} {label.priority} {label.language} | "
            f"{decided} | {'yes' if majority[example] else 'no'} |"
        )
    return "\n".join(lines) + "\n"


def compare_with(earlier: Path, report: Report) -> str:
    before = json.loads(earlier.read_text(encoding="utf-8"))["per_example"]
    after = majority_correct(report.attempts)
    shared = sorted(before.keys() & after.keys())
    fixed = [example for example in shared if not before[example] and after[example]]
    broken = [example for example in shared if before[example] and not after[example]]
    p_value = mcnemar_exact(len(fixed), len(broken))
    return (
        f"Before -> after on {len(shared)} examples: fixed {fixed or 'none'}, "
        f"broken {broken or 'none'}; exact McNemar p = {p_value:.3f}"
    )


def _describe(attempt: Attempt) -> str:
    if attempt.decision is None:
        return "error"
    decision = attempt.decision
    codes = f" [{' '.join(attempt.codes)}]" if attempt.codes else ""
    return f"{decision.action} {decision.category} {decision.priority} {decision.language}{codes}"


def _number(value: object) -> float:
    return float(value) if isinstance(value, int | float) else 0.0


def _sequence(value: object) -> list[object]:
    return list(value) if isinstance(value, list | tuple) else []
