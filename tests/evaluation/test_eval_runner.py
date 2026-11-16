import json
from dataclasses import dataclass, field
from pathlib import Path

from tests.fakes.decisions import HANDOFF, REPLY
from tests.fakes.helpdesk import make_example
from tests.fakes.models import ScriptedModels
from triage.deciders import ProviderOutageError, Verdict
from triage.domain import Ticket
from triage.evaluation.judge import Judge, JudgeVerdict
from triage.evaluation.runner import compare_with, evaluate, summary, write_results
from triage.evaluation.scoring import score
from triage.helpdesk.models import LabelledExample
from triage.knowledge.faq import load_faq

TRACE: dict[str, object] = {
    "cost_usd": 0.001,
    "tokens": 3000,
    "codes": ["MODEL"],
    "calls": [
        {"role": "triage", "model": "openai/gpt-oss-120b", "outcome": "ok"},
        {"role": "vote", "model": "qwen/qwen3.8-27b", "outcome": "bad_request"},
        {"role": "vote", "model": "gemini-3.5-flash-lite", "outcome": "ok"},
    ],
}


@dataclass
class ExampleDecider:
    name: str = "example"
    replies: frozenset[str] = frozenset()
    down: frozenset[str] = frozenset()
    seen: list[str] = field(default_factory=list)

    async def decide(self, ticket: Ticket) -> Verdict:
        self.seen.append(ticket.id)
        if ticket.id in self.down:
            raise ProviderOutageError("every model for triage is down")
        return Verdict(REPLY if ticket.id in self.replies else HANDOFF, TRACE)


def examples() -> list[LabelledExample]:
    return [
        LabelledExample.model_validate(make_example(1)),
        LabelledExample.model_validate(
            make_example(2, action="handoff", category="billing", priority="P2")
        ),
        LabelledExample.model_validate(make_example(3)),
    ]


def passing_judge() -> tuple[Judge, ScriptedModels]:
    models = ScriptedModels()
    models.respond(
        JudgeVerdict,
        lambda spec: JudgeVerdict(
            answers_the_question=True,
            only_uses_the_help_centre=True,
            right_language=True,
            verdict="pass",
            rationale="Answers from the help centre.",
        ),
    )
    return Judge(models.gateway(), load_faq()), models


async def test_every_example_runs_the_requested_number_of_times() -> None:
    decider = ExampleDecider(replies=frozenset({"E01"}))
    attempts = await evaluate(decider, examples(), repeats=3, judge=None)
    assert sorted(decider.seen) == ["E01"] * 3 + ["E02"] * 3 + ["E03"] * 3
    assert len(attempts) == 9


async def test_only_replies_are_judged() -> None:
    judge, models = passing_judge()
    decider = ExampleDecider(replies=frozenset({"E01"}))
    attempts = await evaluate(decider, examples(), repeats=1, judge=judge)
    judged = {attempt.example_id: attempt.judged_good_reply for attempt in attempts}
    assert judged == {"E01": True, "E02": None, "E03": None}
    assert models.called()["JudgeVerdict"] == 1


async def test_an_outage_is_an_error_and_the_other_examples_still_run() -> None:
    decider = ExampleDecider(replies=frozenset({"E01"}), down=frozenset({"E03"}))
    report = score(await evaluate(decider, examples(), repeats=1, judge=None))
    assert report.errors == 1
    assert summary(report)["errors"] == 1
    assert report.fields["action"].correct == 2


async def test_each_attempt_records_the_models_that_answered_and_the_failed_calls() -> None:
    attempts = await evaluate(ExampleDecider(), examples()[:1], repeats=1, judge=None)
    assert attempts[0].models == (
        "triage=openai/gpt-oss-120b",
        "vote=gemini-3.5-flash-lite",
    )
    assert attempts[0].failed_calls == 1


async def test_results_are_written_and_compared_with_an_earlier_run(tmp_path: Path) -> None:
    before = score(await evaluate(ExampleDecider(), examples(), repeats=1, judge=None))
    write_results(tmp_path / "before", before, title="Eval: before", notes={"repeats": 1})
    after_decider = ExampleDecider(replies=frozenset({"E01", "E03"}))
    after = score(await evaluate(after_decider, examples(), repeats=1, judge=None))

    written = json.loads((tmp_path / "before.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / "before.md").read_text(encoding="utf-8")
    comparison = compare_with(tmp_path / "before.json", after)

    assert written["per_example"] == {"E01": False, "E02": True, "E03": False}
    assert written["attempts"][0]["failed_calls"] == 1
    assert markdown.startswith("# Eval: before")
    assert "| E02 |" in markdown
    assert "fixed ['E01', 'E03'], broken none" in comparison
