from datetime import datetime

from pydantic import BaseModel, ConfigDict

from triage.domain import Action, Category, Language, Priority, Ticket


class TicketPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    tickets: list[Ticket]
    next_cursor: str | None = None


class TicketDetail(Ticket):
    handled: object = None

    @property
    def is_handled(self) -> bool:
        return self.handled is not None and self.handled is not False


class Label(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    language: Language
    category: Category
    priority: Priority
    action: Action
    reason: str = ""


class LabelledExample(Ticket):
    label: Label


class ExamplesPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    examples: list[LabelledExample]


class HelpdeskStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    mode: str
    candidate: str
    open_tickets: int
    handled_tickets: int
    live_ends_at: datetime | None = None
