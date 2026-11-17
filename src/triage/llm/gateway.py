import asyncio
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import httpx
import openai
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, SecretStr

from triage.config import ModelSettings
from triage.deciders import ProviderOutageError
from triage.helpdesk.pacing import Clock, Sleep
from triage.llm.limits import RateWindow
from triage.llm.roster import BASE_URLS, PROMPT_GUARD, ModelSpec, Provider

type Messages = Sequence[tuple[str, str]]
type RunnableFactory = Callable[[ModelSpec, type[BaseModel] | None], Runnable[Any, Any]]

ATTEMPTS_PER_MODEL = 2
RETRY_PAUSE_SECONDS = 2.0
GUARD_SEGMENT_CHARS = 1500
GUARD_MAX_SEGMENTS = 4
WAIT_WORTH_REPORTING_SECONDS = 1.0
_PROVIDER_ERRORS = (openai.APIError, httpx.HTTPError)
# The OpenAI SDK parses structured output itself and raises when a provider lets a malformed
# answer through (pydantic's ValidationError is a ValueError) or stops at the token limit.
_UNUSABLE_ANSWERS = (
    ValueError,
    openai.LengthFinishReasonError,
    openai.ContentFilterFinishReasonError,
)
_OUTCOMES = {
    "unparseable": "broken JSON",
    "rate_limited": "rate limited",
    "exhausted": "daily limit reached",
    "rejected": "key or model rejected",
    "bad_request": "bad request",
    "unavailable": "no response",
}

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CallRecord:
    role: str
    model: str
    outcome: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: float


@dataclass(frozen=True, slots=True)
class Answer[SchemaT: BaseModel]:
    value: SchemaT
    spec: ModelSpec


class AllModelsFailedError(ProviderOutageError):
    pass


class ModelGateway:
    def __init__(
        self,
        settings: ModelSettings,
        *,
        factory: RunnableFactory | None = None,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._keys: dict[Provider, SecretStr] = {
            Provider.GROQ: settings.groq_api_key,
            Provider.GEMINI: settings.gemini_api_key,
        }
        self._factory = factory or self._langchain_runnable
        self._clock = clock
        self._sleep = sleep
        self._windows: dict[str, RateWindow] = {}
        self._unavailable: set[str] = set()

    async def structured[SchemaT: BaseModel](
        self,
        role: str,
        schema: type[SchemaT],
        messages: Messages,
        candidates: Sequence[ModelSpec],
        calls: list[CallRecord],
    ) -> Answer[SchemaT]:
        for spec in candidates:
            for attempt in range(ATTEMPTS_PER_MODEL):
                if spec.model in self._unavailable:
                    break
                if attempt:
                    await self._sleep(RETRY_PAUSE_SECONDS)
                answer = await self._attempt(role, schema, messages, spec, calls)
                if answer is not None:
                    return answer
                outcome = calls[-1].outcome
                log.info(
                    "%s gave no usable %s answer (%s)",
                    spec.short_name,
                    role,
                    _OUTCOMES.get(outcome, outcome),
                )
        raise AllModelsFailedError(f"every model for {role} failed")

    async def _attempt[SchemaT: BaseModel](
        self,
        role: str,
        schema: type[SchemaT],
        messages: Messages,
        spec: ModelSpec,
        calls: list[CallRecord],
    ) -> Answer[SchemaT] | None:
        await self._reserve(spec, _estimated_tokens(messages) + spec.max_tokens)
        started = time.perf_counter()
        try:
            result = await self._factory(spec, schema).ainvoke(list(messages))
        except _PROVIDER_ERRORS as error:
            calls.append(self._failed_call(role, spec, error, started))
            return None
        except _UNUSABLE_ANSWERS:
            calls.append(
                CallRecord(role, spec.model, "unparseable", 0, 0, _elapsed_ms(started), 0.0)
            )
            return None
        raw = result.get("raw") if isinstance(result, dict) else None
        parsed = result.get("parsed") if isinstance(result, dict) else None
        if isinstance(parsed, schema):
            calls.append(_record(role, spec, "ok", raw, started))
            return Answer(parsed, spec)
        calls.append(_record(role, spec, "unparseable", raw, started))
        return None

    async def injection_probability(self, text: str, calls: list[CallRecord]) -> float | None:
        if PROMPT_GUARD.model in self._unavailable:
            return None
        segments = [
            text[start : start + GUARD_SEGMENT_CHARS]
            for start in range(0, max(len(text), 1), GUARD_SEGMENT_CHARS)
        ][:GUARD_MAX_SEGMENTS]
        scores: list[float] = []
        for segment in segments:
            await self._reserve(PROMPT_GUARD, _estimated_tokens([("user", segment)]) + 16)
            started = time.perf_counter()
            try:
                message = await self._factory(PROMPT_GUARD, None).ainvoke([("user", segment)])
                scores.append(float(str(message.content).strip()))
            except (*_PROVIDER_ERRORS, ValueError) as error:
                calls.append(self._failed_call("guard", PROMPT_GUARD, error, started))
                return None
            calls.append(_record("guard", PROMPT_GUARD, "ok", message, started))
        return max(scores, default=None)

    def _failed_call(
        self, role: str, spec: ModelSpec, error: Exception, started: float
    ) -> CallRecord:
        outcome = _classify(error)
        if outcome in {"exhausted", "rejected"}:
            self._unavailable.add(spec.model)
        return CallRecord(role, spec.model, outcome, 0, 0, _elapsed_ms(started), 0.0)

    async def _reserve(self, spec: ModelSpec, tokens: int) -> None:
        window = self._window(spec)
        wait = window.seconds_until_free(tokens)
        if wait >= WAIT_WORTH_REPORTING_SECONDS:
            log.info(
                "waiting about %.0f s for %s: it allows %s tokens a minute",
                wait,
                spec.short_name,
                f"{spec.tokens_per_minute:,}",
            )
        await window.acquire(tokens)

    def _window(self, spec: ModelSpec) -> RateWindow:
        if spec.model not in self._windows:
            self._windows[spec.model] = RateWindow(
                tokens_per_minute=spec.tokens_per_minute,
                requests_per_minute=spec.requests_per_minute,
                clock=self._clock,
                sleep=self._sleep,
            )
        return self._windows[spec.model]

    def _langchain_runnable(
        self, spec: ModelSpec, schema: type[BaseModel] | None
    ) -> Runnable[Any, Any]:
        model = ChatOpenAI(
            openai_api_base=BASE_URLS[spec.provider],
            openai_api_key=self._keys[spec.provider],
            model_name=spec.model,
            temperature=0,
            max_tokens=spec.max_tokens,
            max_retries=1,
            request_timeout=45,
            **spec.options,
        )
        if schema is None:
            return model
        return model.with_structured_output(
            schema, method="json_schema", strict=True, include_raw=True
        )


def _classify(error: Exception) -> str:
    if isinstance(error, openai.RateLimitError):
        text = str(error).lower()
        return "exhausted" if "per day" in text or "quota" in text else "rate_limited"
    if isinstance(
        error, openai.AuthenticationError | openai.PermissionDeniedError | openai.NotFoundError
    ):
        return "rejected"
    if isinstance(error, openai.BadRequestError):
        return "bad_request"
    return "unavailable"


def _record(
    role: str, spec: ModelSpec, outcome: str, message: object, started: float
) -> CallRecord:
    usage = message.usage_metadata if isinstance(message, AIMessage) else None
    input_tokens = int(usage["input_tokens"]) if usage else 0
    output_tokens = int(usage["output_tokens"]) if usage else 0
    return CallRecord(
        role,
        spec.model,
        outcome,
        input_tokens,
        output_tokens,
        _elapsed_ms(started),
        spec.cost_usd(input_tokens, output_tokens),
    )


def _estimated_tokens(messages: Messages) -> int:
    return sum(len(content) for _, content in messages) // 4 + 1


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
