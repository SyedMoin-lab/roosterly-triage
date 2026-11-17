from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx2
import openai
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel

from tests.fakes.clock import FakeClock
from triage.config import ModelSettings
from triage.llm.gateway import ModelGateway
from triage.llm.roster import ModelSpec

type Responder = Callable[[ModelSpec], BaseModel]

SETTINGS = ModelSettings.model_validate(
    {"groq_api_key": "test-groq-key", "gemini_api_key": "test-gemini-key"}
)


@dataclass
class ScriptedModels:
    responders: dict[str, Responder] = field(default_factory=dict)
    down: set[str] = field(default_factory=set)
    hiccups: Counter[str] = field(default_factory=Counter)
    errors: dict[str, Exception] = field(default_factory=dict)  # model name -> error it raises
    injection_probability: float = 0.001
    calls: list[tuple[str, str]] = field(default_factory=list)

    def respond(self, schema: type[BaseModel], responder: Responder) -> None:
        self.responders[schema.__name__] = responder

    def gateway(self) -> ModelGateway:
        clock = FakeClock()
        return ModelGateway(SETTINGS, factory=self.factory, clock=clock, sleep=clock.sleep)

    def called(self) -> Counter[str]:
        return Counter(schema for _, schema in self.calls)

    def factory(self, spec: ModelSpec, schema: type[BaseModel] | None) -> Runnable[Any, Any]:
        async def respond(messages: object) -> object:
            name = schema.__name__ if schema else "Guard"
            self.calls.append((spec.model, name))
            if spec.model in self.errors:
                raise self.errors[spec.model]
            if spec.model in self.down or self.hiccups[spec.model] > 0:
                self.hiccups[spec.model] -= 1
                raise openai.APIConnectionError(request=httpx2.Request("POST", "https://test"))
            usage = {"input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200}
            if schema is None:
                return AIMessage(content=str(self.injection_probability), usage_metadata=usage)
            raw = AIMessage(content="{}", usage_metadata=usage)
            return {"parsed": self.responders[name](spec), "raw": raw, "parsing_error": None}

        return RunnableLambda(respond)
