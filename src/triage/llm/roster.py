from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

PRICES_AS_OF = "2026-11-16"


class Provider(StrEnum):
    GROQ = "groq"
    GEMINI = "gemini"


BASE_URLS = {
    Provider.GROQ: "https://api.groq.com/openai/v1",
    Provider.GEMINI: "https://generativelanguage.googleapis.com/v1beta/openai/",
}


@dataclass(frozen=True, slots=True)
class ModelSpec:
    provider: Provider
    model: str
    family: str
    max_tokens: int
    tokens_per_minute: int
    requests_per_minute: int
    usd_per_million_input: float
    usd_per_million_output: float
    options: Mapping[str, Any] = field(default_factory=dict)

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.usd_per_million_input + output_tokens * self.usd_per_million_output
        ) / 1_000_000


QWEN = ModelSpec(
    Provider.GROQ,
    "qwen/qwen3.8-27b",
    family="qwen",
    max_tokens=800,
    tokens_per_minute=7200,
    requests_per_minute=28,
    usd_per_million_input=0.80,
    usd_per_million_output=4.00,
    options={"extra_body": {"reasoning_format": "hidden"}},
)
GPT_OSS = ModelSpec(
    Provider.GROQ,
    "openai/gpt-oss-120b",
    family="gpt-oss",
    max_tokens=1200,
    tokens_per_minute=7200,
    requests_per_minute=28,
    usd_per_million_input=0.35,
    usd_per_million_output=0.75,
    options={"reasoning_effort": "low"},
)
FLASH_LITE = ModelSpec(
    Provider.GEMINI,
    "gemini-3.5-flash-lite",
    family="gemini",
    max_tokens=2000,
    tokens_per_minute=200_000,
    requests_per_minute=14,
    usd_per_million_input=0.10,
    usd_per_million_output=0.40,
)
SAFEGUARD = ModelSpec(
    Provider.GROQ,
    "openai/gpt-oss-safeguard-20b",
    family="gpt-oss",
    max_tokens=500,
    tokens_per_minute=1800,
    requests_per_minute=28,
    usd_per_million_input=0.075,
    usd_per_million_output=0.30,
    options={"reasoning_effort": "low"},
)
PROMPT_GUARD = ModelSpec(
    Provider.GROQ,
    "meta-llama/llama-prompt-guard-2-86m",
    family="prompt-guard",
    max_tokens=16,
    tokens_per_minute=14_000,
    requests_per_minute=28,
    usd_per_million_input=0.04,
    usd_per_million_output=0.04,
)

TRIAGE_MODELS = (GPT_OSS, QWEN, FLASH_LITE)
VOTING_MODELS = (GPT_OSS, FLASH_LITE, QWEN)
DRAFTING_MODELS = (QWEN, FLASH_LITE, GPT_OSS)
VERIFYING_MODELS = (FLASH_LITE, GPT_OSS, QWEN)
JUDGING_MODELS = (GPT_OSS, FLASH_LITE, QWEN)
AUDIT_MODELS = (SAFEGUARD,)


def other_families(models: tuple[ModelSpec, ...], *excluded: str) -> tuple[ModelSpec, ...]:
    return tuple(spec for spec in models if spec.family not in excluded)
