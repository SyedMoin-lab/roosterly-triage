import logging
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TextIO

PACKAGE_LOGGER = "triage"

_ticket: ContextVar[str] = ContextVar("triage_ticket", default="")


@contextmanager
def ticket_scope(ticket_id: str) -> Iterator[None]:
    token = _ticket.set(ticket_id)
    try:
        yield
    finally:
        _ticket.reset(token)


class TicketFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.__dict__.setdefault("ticket", _ticket.get())
        return True


class ProgressFormatter(logging.Formatter):
    def __init__(self, started: float) -> None:
        super().__init__()
        self._started = started

    def format(self, record: logging.LogRecord) -> str:
        minutes, seconds = divmod(max(int(record.created - self._started), 0), 60)
        ticket = record.__dict__.get("ticket", "")
        return f"{minutes:3d}:{seconds:02d}  {ticket:<6} {record.getMessage()}"


@contextmanager
def show_progress(stream: TextIO | None = None) -> Iterator[None]:
    logger = logging.getLogger(PACKAGE_LOGGER)
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.addFilter(TicketFilter())
    handler.setFormatter(ProgressFormatter(time.time()))
    level, propagate = logger.level, logger.propagate
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        yield
    finally:
        logger.removeHandler(handler)
        logger.setLevel(level)
        logger.propagate = propagate
