import re
from datetime import datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SAFE_TICKET_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


class Language(StrEnum):
    DUTCH = "nl"
    ENGLISH = "en"
    GERMAN = "de"


class Category(StrEnum):
    BUG = "bug"
    BILLING = "billing"
    FEATURE_REQUEST = "feature_request"
    QUESTION = "question"
    OTHER = "other"


class Priority(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class Action(StrEnum):
    REPLY = "reply"
    HANDOFF = "handoff"
    CLOSE = "close"


def safe_ticket_id(value: str) -> str:
    if not _SAFE_TICKET_ID.fullmatch(value):
        raise ValueError(f"unsafe ticket id: {value!r}")
    return value


class Ticket(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str
    received_at: datetime
    channel: str = ""
    customer_plan: str = ""
    subject: str = ""
    body: str = ""

    @field_validator("id")
    @classmethod
    def _id_is_safe_in_urls(cls, value: str) -> str:
        return safe_ticket_id(value)

    @field_validator("channel", "customer_plan", "subject", "body", mode="before")
    @classmethod
    def _missing_text_is_empty(cls, value: object) -> object:
        return "" if value is None else value


class Decision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    action: Action
    language: Language
    category: Category
    priority: Priority
    reason: str = Field(min_length=1, max_length=500)
    draft_reply: str | None = Field(default=None, min_length=1)
    handoff_note: str | None = Field(default=None, min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _fields_match_action(self) -> Self:
        if (self.action is Action.REPLY) != (self.draft_reply is not None):
            raise ValueError("draft_reply is required for a reply and only for a reply")
        if (self.action is Action.HANDOFF) != (self.handoff_note is not None):
            raise ValueError("handoff_note is required for a handoff and only for a handoff")
        return self

    def request_body(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"action"}, exclude_none=True)
