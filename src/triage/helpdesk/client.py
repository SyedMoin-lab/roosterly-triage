import asyncio
import random
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Self

import httpx
from pydantic import BaseModel, ValidationError

from triage import __version__
from triage.config import HelpdeskSettings
from triage.domain import Decision, Ticket, safe_ticket_id
from triage.helpdesk.errors import (
    AlreadyHandledError,
    AuthenticationError,
    ConnectionFailedError,
    HelpdeskError,
    NotFoundError,
    ProtocolViolationError,
    RateLimitedError,
    RequestRejectedError,
    ServiceUnavailableError,
    ValidationFailedError,
    WriteOutcomeUnknownError,
)
from triage.helpdesk.models import (
    ExamplesPage,
    HelpdeskStatus,
    LabelledExample,
    TicketDetail,
    TicketPage,
)
from triage.helpdesk.pacing import Pacer, Sleep
from triage.helpdesk.retry import RetryPolicy

PAGE_SIZE = 10
MAX_PAGES = 100
CONNECT_TIMEOUT_SECONDS = 5.0
DEFAULT_RETRY = RetryPolicy()
_NEVER_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


def build_http_client(
    settings: HelpdeskSettings,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.helpdesk_base_url,
        headers={
            "Authorization": f"Bearer {settings.helpdesk_api_key.get_secret_value()}",
            "X-Candidate-Email": settings.candidate_email,
            "Accept": "application/json",
            "User-Agent": f"roosterly-triage/{__version__}",
        },
        timeout=httpx.Timeout(settings.helpdesk_timeout_seconds, connect=CONNECT_TIMEOUT_SECONDS),
        transport=transport,
        follow_redirects=False,
    )


class HelpdeskClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        pacer: Pacer,
        retry: RetryPolicy = DEFAULT_RETRY,
        sleep: Sleep = asyncio.sleep,
        rng: random.Random | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._http = http
        self._pacer = pacer
        self._retry = retry
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._now = now

    @classmethod
    def from_settings(cls, settings: HelpdeskSettings) -> Self:
        return cls(build_http_client(settings), pacer=Pacer(settings.helpdesk_requests_per_second))

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._http.aclose()

    async def status(self) -> HelpdeskStatus:
        return _parse(HelpdeskStatus, await self._get_json("/status"), "GET /status")

    async def examples(self) -> list[LabelledExample]:
        return _parse(ExamplesPage, await self._get_json("/examples"), "GET /examples").examples

    async def open_tickets(self) -> list[Ticket]:
        tickets: dict[str, Ticket] = {}
        seen_cursors: set[str] = set()
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            params = {"limit": str(PAGE_SIZE), "status": "open"}
            if cursor is not None:
                params["cursor"] = cursor
            page = _parse(TicketPage, await self._get_json("/tickets", params), "GET /tickets")
            for ticket in page.tickets:
                tickets.setdefault(ticket.id, ticket)
            if page.next_cursor is None:
                return list(tickets.values())
            if page.next_cursor in seen_cursors:
                raise ProtocolViolationError(f"pagination cursor repeated: {page.next_cursor!r}")
            seen_cursors.add(page.next_cursor)
            cursor = page.next_cursor
        raise ProtocolViolationError(f"pagination did not finish within {MAX_PAGES} pages")

    async def ticket(self, ticket_id: str) -> TicketDetail:
        path = f"/tickets/{safe_ticket_id(ticket_id)}"
        return _parse(TicketDetail, await self._get_json(path), f"GET {path}")

    async def submit(self, ticket_id: str, decision: Decision) -> None:
        path = f"/tickets/{safe_ticket_id(ticket_id)}/{decision.action.value}"
        await self._send("POST", path, is_write=True, json=decision.request_body())

    async def reset_practice(self) -> None:
        await self._send("POST", "/practice/reset", is_write=True)

    async def _get_json(self, path: str, params: Mapping[str, str] | None = None) -> object:
        response = await self._send("GET", path, is_write=False, params=params)
        try:
            return response.json()
        except ValueError as error:
            raise ProtocolViolationError(f"GET {path} returned a body that is not JSON") from error

    async def _send(
        self,
        method: str,
        path: str,
        *,
        is_write: bool,
        params: Mapping[str, str] | None = None,
        json: Mapping[str, Any] | None = None,
    ) -> httpx.Response:
        request = f"{method} {path}"
        attempt = 0
        while True:
            attempt += 1
            await self._pacer.wait_turn()
            cause: BaseException | None = None
            try:
                response = await self._http.request(method, path, params=params, json=json)
            except httpx.TransportError as transport_error:
                error = _transport_failure(transport_error, request, is_write=is_write)
                cause = transport_error
            else:
                if response.is_success:
                    return response
                error = self._response_failure(response, request, is_write=is_write)
            if not error.retryable or attempt >= self._retry.max_attempts:
                raise error from cause
            await self._sleep(self._delay_before_retry(error, attempt))

    def _delay_before_retry(self, error: HelpdeskError, retry_number: int) -> float:
        if isinstance(error, RateLimitedError):
            return error.retry_after
        return self._retry.backoff(retry_number, self._rng)

    def _response_failure(
        self,
        response: httpx.Response,
        request: str,
        *,
        is_write: bool,
    ) -> HelpdeskError:
        status = response.status_code
        code, message, problems = _error_details(response)
        text = f"{request} -> HTTP {status}" + (f" {code}" if code else "")
        if message:
            text += f": {message}"
        match status:
            case 429:
                seconds = self._retry.retry_after(response.headers.get("Retry-After"), self._now())
                self._pacer.pause(seconds)
                return RateLimitedError(text, retry_after=seconds, status=status, code=code)
            case 503:
                return ServiceUnavailableError(text, status=status, code=code)
            case 401:
                return AuthenticationError(text, status=status, code=code)
            case 404:
                return NotFoundError(text, status=status, code=code)
            case 409:
                return AlreadyHandledError(text, status=status, code=code)
            case 422:
                return ValidationFailedError(text, problems=problems, status=status, code=code)
            case _ if status >= 500 and is_write:
                return WriteOutcomeUnknownError(text, status=status, code=code)
            case _ if status >= 500:
                return ServiceUnavailableError(text, status=status, code=code)
            case _:
                return RequestRejectedError(text, status=status, code=code)


def _transport_failure(
    error: httpx.TransportError,
    request: str,
    *,
    is_write: bool,
) -> HelpdeskError:
    kind = type(error).__name__
    if isinstance(error, _NEVER_SENT):
        return ConnectionFailedError(f"{request}: could not connect ({kind})")
    if is_write:
        return WriteOutcomeUnknownError(f"{request}: no response after sending ({kind})")
    return ConnectionFailedError(f"{request}: no response ({kind})")


def _error_details(response: httpx.Response) -> tuple[str | None, str, list[object]]:
    try:
        body = response.json()
    except ValueError:
        return None, "", []
    if not isinstance(body, dict):
        return None, "", []
    code = body.get("error")
    message = body.get("message")
    problems = body.get("problems")
    return (
        code if isinstance(code, str) else None,
        message[:200] if isinstance(message, str) else "",
        problems if isinstance(problems, list) else [],
    )


def _parse[ModelT: BaseModel](model: type[ModelT], data: object, source: str) -> ModelT:
    try:
        return model.model_validate(data)
    except ValidationError as error:
        raise ProtocolViolationError(
            f"{source} returned an unexpected shape ({error.error_count()} problems)"
        ) from error
