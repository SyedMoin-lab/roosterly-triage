import logging

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


def test_the_rate_window_predicts_no_wait_while_there_is_room() -> None:
    clock = FakeClock()
    window = RateWindow(
        tokens_per_minute=1000, requests_per_minute=10, clock=clock, sleep=clock.sleep
    )
    assert window.seconds_until_free(1000) == 0.0


async def test_the_rate_window_predicts_the_wait_until_enough_tokens_expire() -> None:
    clock = FakeClock()
    window = RateWindow(
        tokens_per_minute=1000, requests_per_minute=10, clock=clock, sleep=clock.sleep
    )
    await window.acquire(400)
    clock.now += 10
    await window.acquire(400)
    clock.now += 5
    assert window.seconds_until_free(200) == 0.0
    assert window.seconds_until_free(500) == 45.0
    assert window.seconds_until_free(1000) == 55.0


async def test_the_predicted_wait_for_a_request_slot_is_the_wait_that_follows() -> None:
    clock = FakeClock()
    window = RateWindow(
        tokens_per_minute=100_000, requests_per_minute=2, clock=clock, sleep=clock.sleep
    )
    await window.acquire(10)
    clock.now += 20
    await window.acquire(10)
    predicted = window.seconds_until_free(10)
    started = clock.now
    await window.acquire(10)
    assert predicted == 40.0
    assert clock.now - started == pytest.approx(predicted)


async def test_a_wait_for_a_rate_limit_is_reported(caplog: pytest.LogCaptureFixture) -> None:
    models = ScriptedModels()
    models.respond(TriageProposal, lambda spec: proposal())
    gateway = models.gateway()
    calls: list[CallRecord] = []
    with caplog.at_level(logging.INFO, logger="triage"):
        for _ in range(8):
            await gateway.structured("triage", TriageProposal, MESSAGES, (GPT_OSS,), calls)
    waits = [message for message in caplog.messages if message.startswith("waiting about")]
    assert waits == ["waiting about 60 s for gpt-oss-120b: it allows 7,200 tokens a minute"]


async def test_a_model_without_a_usable_answer_is_reported(
    caplog: pytest.LogCaptureFixture,
) -> None:
    models = ScriptedModels()
    models.respond(TriageProposal, lambda spec: proposal())
    models.down = {GPT_OSS.model}
    calls: list[CallRecord] = []
    with caplog.at_level(logging.INFO, logger="triage"):
        answer = await models.gateway().structured(
            "triage", TriageProposal, MESSAGES, (GPT_OSS, QWEN), calls
        )
    assert answer.spec is QWEN
    assert caplog.messages.count("gpt-oss-120b gave no usable triage answer (no response)") == 2


async def test_a_malformed_answer_a_provider_let_through_goes_to_the_next_model() -> None:
    models = ScriptedModels(errors={GPT_OSS.model: ValueError("faq_id: field required")})
    models.respond(TriageProposal, lambda spec: proposal())
    calls: list[CallRecord] = []
    answer = await models.gateway().structured(
        "triage", TriageProposal, MESSAGES, (GPT_OSS, QWEN), calls
    )
    assert answer.spec is QWEN
    assert [call.outcome for call in calls] == ["unparseable", "unparseable", "ok"]
