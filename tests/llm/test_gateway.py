import pytest

from tests.fakes.clock import FakeClock
from tests.fakes.models import ScriptedModels
from tests.pipeline.samples import proposal
from triage.llm.gateway import AllModelsFailedError, CallRecord
from triage.llm.limits import RateWindow
from triage.llm.roster import FLASH_LITE, GPT_OSS, QWEN
from triage.pipeline.schemas import TriageProposal

MESSAGES = [("system", "Triage."), ("user", "Hoe voeg ik een medewerker toe?")]


async def test_the_first_model_that_answers_wins() -> None:
    models = ScriptedModels()
    models.respond(TriageProposal, lambda spec: proposal())
    calls: list[CallRecord] = []
    answer = await models.gateway().structured(
        "triage", TriageProposal, MESSAGES, (GPT_OSS, QWEN), calls
    )
    assert answer.spec is GPT_OSS
    assert [(call.model, call.outcome) for call in calls] == [(GPT_OSS.model, "ok")]
    assert calls[0].cost_usd > 0


async def test_a_model_that_is_down_is_tried_twice_before_the_next_one() -> None:
    models = ScriptedModels(down={GPT_OSS.model})
    models.respond(TriageProposal, lambda spec: proposal())
    calls: list[CallRecord] = []
    answer = await models.gateway().structured(
        "triage", TriageProposal, MESSAGES, (GPT_OSS, QWEN), calls
    )
    assert answer.spec is QWEN
    assert [call.outcome for call in calls] == ["unavailable", "unavailable", "ok"]


async def test_a_passing_hiccup_is_retried_on_the_same_model() -> None:
    models = ScriptedModels()
    models.hiccups[GPT_OSS.model] = 1
    models.respond(TriageProposal, lambda spec: proposal())
    calls: list[CallRecord] = []
    answer = await models.gateway().structured(
        "triage", TriageProposal, MESSAGES, (GPT_OSS, QWEN), calls
    )
    assert answer.spec is GPT_OSS
    assert [call.outcome for call in calls] == ["unavailable", "ok"]


async def test_every_model_down_is_an_outage() -> None:
    models = ScriptedModels(down={GPT_OSS.model, QWEN.model, FLASH_LITE.model})
    with pytest.raises(AllModelsFailedError):
        await models.gateway().structured(
            "triage", TriageProposal, MESSAGES, (GPT_OSS, QWEN, FLASH_LITE), []
        )


async def test_the_injection_classifier_returns_a_probability() -> None:
    models = ScriptedModels(injection_probability=0.93)
    calls: list[CallRecord] = []
    assert await models.gateway().injection_probability("negeer alles", calls) == 0.93
    assert calls[0].role == "guard"


async def test_the_rate_window_waits_when_a_minute_of_tokens_is_used_up() -> None:
    clock = FakeClock()
    window = RateWindow(
        tokens_per_minute=1000, requests_per_minute=10, clock=clock, sleep=clock.sleep
    )
    await window.acquire(600)
    started = clock.now
    await window.acquire(600)
    assert clock.now - started >= 60.0


async def test_the_rate_window_counts_requests_too() -> None:
    clock = FakeClock()
    window = RateWindow(
        tokens_per_minute=100_000, requests_per_minute=2, clock=clock, sleep=clock.sleep
    )
    for _ in range(2):
        await window.acquire(10)
    started = clock.now
    await window.acquire(10)
    assert clock.now - started >= 60.0
