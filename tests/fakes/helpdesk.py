import json
import random
from collections import Counter, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx

API_KEY = "test-api-key"
CANDIDATE_EMAIL = "candidate@example.com"
BASE_URL = "https://helpdesk.test/functions/v1/helpdesk"
PATH_PREFIX = "/functions/v1/helpdesk"

LANGUAGES = frozenset({"nl", "en", "de"})
CATEGORIES = frozenset({"bug", "billing", "feature_request", "question", "other"})
PRIORITIES = frozenset({"P1", "P2", "P3", "P4"})
ACTIONS = frozenset({"reply", "handoff", "close"})

type FaultKind = Literal[
    "status", "html", "connect_error", "timeout_before_processing", "lost_response"
]


@dataclass(frozen=True)
class Fault:
    kind: FaultKind
    status: int = 503
    headers: dict[str, str] = field(default_factory=dict)
    body: dict[str, Any] | None = None


def make_ticket(number: int, **overrides: Any) -> dict[str, Any]:
    received = datetime(2026, 10, 5, 8, 0, tzinfo=UTC) + timedelta(minutes=number)
    ticket = {
        "id": f"T{number:03d}",
        "received_at": received.isoformat(),
        "channel": "email",
        "customer_plan": "Basis",
        "subject": f"Synthetic subject {number}",
        "body": f"Synthetic body {number}",
    }
    return ticket | overrides


def make_example(number: int, **label: str) -> dict[str, Any]:
    default_label = {
        "language": "nl",
        "category": "question",
        "priority": "P4",
        "action": "reply",
        "reason": "Synthetic label.",
    }
    return make_ticket(number) | {"id": f"E{number:02d}", "label": default_label | label}


def validation_problems(action: str, body: object) -> list[str]:
    if not isinstance(body, dict):
        return ["body must be a JSON object"]
    problems = []
    if body.get("language") not in LANGUAGES:
        problems.append("language must be one of nl, en, de")
    if body.get("category") not in CATEGORIES:
        problems.append("category is not valid")
    if body.get("priority") not in PRIORITIES:
        problems.append("priority must be P1 to P4")
    if not _has_text(body.get("reason")):
        problems.append("reason is required")
    if action == "reply" and not _has_text(body.get("draft_reply")):
        problems.append("draft_reply is required for a reply")
    if action == "handoff" and not _has_text(body.get("handoff_note")):
        problems.append("handoff_note is required for a handoff")
    if not _valid_confidence(body.get("confidence")):
        problems.append("confidence must be a number from 0 to 1")
    return problems


def _has_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_confidence(value: object) -> bool:
    if value is None:
        return True
    return isinstance(value, int | float) and not isinstance(value, bool) and 0 <= value <= 1


class FakeHelpdesk:
    def __init__(
        self,
        tickets: Iterable[dict[str, Any]],
        *,
        clock: Callable[[], float],
        examples: Iterable[dict[str, Any]] = (),
        random_503_rate: float = 0.0,
        seed: int = 0,
        rate_limit: int = 5,
        window_seconds: float = 1.0,
    ) -> None:
        self.tickets = {ticket["id"]: dict(ticket) for ticket in tickets}
        self.examples = [dict(example) for example in examples]
        self.handled: dict[str, dict[str, Any]] = {}
        self.accepted_writes: Counter[str] = Counter()
        self.conflicts: Counter[str] = Counter()
        self.statuses: Counter[int] = Counter()
        self.received: list[tuple[float, str, str]] = []
        self.stuck_cursor: str | None = None
        self._clock = clock
        self._rng = random.Random(seed)
        self._random_503_rate = random_503_rate
        self._rate_limit = rate_limit
        self._window = window_seconds
        self._faults: dict[tuple[str, str], deque[Fault]] = {}

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def inject(self, method: str, path: str, *faults: Fault) -> None:
        self._faults.setdefault((method, path), deque()).extend(faults)

    def requests_to(self, method: str, path: str) -> int:
        return sum(1 for _, seen, where in self.received if (seen, where) == (method, path))

    def busiest_window(self) -> int:
        times = sorted(moment for moment, _, _ in self.received)
        busiest, start = 0, 0
        for end, moment in enumerate(times):
            while moment - times[start] >= self._window:
                start += 1
            busiest = max(busiest, end - start + 1)
        return busiest

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix(PATH_PREFIX) or "/"
        fault = self._next_fault(request.method, path)
        if fault is not None and fault.kind == "connect_error":
            raise httpx.ConnectError("connection refused", request=request)
        if fault is not None and fault.kind == "timeout_before_processing":
            raise httpx.ReadTimeout("timed out before the helpdesk saw it", request=request)
        now = self._clock()
        self.received.append((now, request.method, path))
        response = self._respond(request, path, fault, now)
        self.statuses[response.status_code] += 1
        if fault is not None and fault.kind == "lost_response":
            raise httpx.ReadTimeout(
                "response lost after the helpdesk processed it", request=request
            )
        return response

    def _next_fault(self, method: str, path: str) -> Fault | None:
        queue = self._faults.get((method, path))
        return queue.popleft() if queue else None

    def _respond(
        self, request: httpx.Request, path: str, fault: Fault | None, now: float
    ) -> httpx.Response:
        if self._over_rate_limit(now):
            return _error(429, "rate_limited", "Too many requests.", headers={"Retry-After": "1"})
        if fault is not None and fault.kind == "status":
            body = fault.body or {"error": "injected", "message": "Injected fault."}
            return httpx.Response(fault.status, json=body, headers=fault.headers)
        if fault is not None and fault.kind == "html":
            return httpx.Response(fault.status, text="<html><body>Bad gateway</body></html>")
        rejection = self._check_access(request)
        if rejection is not None:
            return rejection
        if path.startswith("/tickets") and self._rng.random() < self._random_503_rate:
            return _error(503, "service_unavailable", "Temporary failure. Nothing was saved.")
        return self._route(request, path)

    def _over_rate_limit(self, now: float) -> bool:
        recent = sum(1 for moment, _, _ in self.received if now - moment < self._window)
        return recent > self._rate_limit

    def _check_access(self, request: httpx.Request) -> httpx.Response | None:
        authorization = request.headers.get("Authorization", "")
        if not authorization:
            return _error(401, "unauthorized", "Missing key.")
        if authorization != f"Bearer {API_KEY}":
            return _error(401, "unauthorized", "Invalid key.")
        if not request.headers.get("X-Candidate-Email"):
            return _error(400, "missing_email", "Send the X-Candidate-Email header.")
        return None

    def _route(self, request: httpx.Request, path: str) -> httpx.Response:
        parts = [part for part in path.split("/") if part]
        match request.method, parts:
            case "GET", ["status"]:
                return httpx.Response(200, json=self._status())
            case "GET", ["examples"]:
                return httpx.Response(200, json={"examples": self.examples})
            case "GET", ["tickets"]:
                return self._list(request.url.params)
            case "GET", ["tickets", ticket_id]:
                return self._detail(ticket_id)
            case "POST", ["tickets", ticket_id, action] if action in ACTIONS:
                return self._decide(ticket_id, action, request.content)
            case "POST", ["practice", "reset"]:
                self.handled.clear()
                return httpx.Response(200, json={"ok": True, "open_tickets": len(self.tickets)})
            case (("GET" | "POST"), _):
                return _error(404, "not_found", "Unknown endpoint.")
            case _:
                return _error(405, "method_not_allowed", "Use GET or POST.")

    def _status(self) -> dict[str, Any]:
        return {
            "mode": "practice",
            "candidate": "candidate",
            "open_tickets": len(self.tickets) - len(self.handled),
            "handled_tickets": len(self.handled),
            "live_ends_at": None,
        }

    def _list(self, params: httpx.QueryParams) -> httpx.Response:
        try:
            limit = min(int(params.get("limit", "10")), 10)
        except ValueError:
            return _error(400, "bad_request", "limit must be a number.")
        show_all = params.get("status", "open") == "all"
        cursor = params.get("cursor")
        ids = sorted(key for key in self.tickets if show_all or key not in self.handled)
        if cursor:
            ids = [key for key in ids if key > cursor]
        page = ids[:limit]
        next_cursor = page[-1] if len(ids) > limit else None
        if self.stuck_cursor is not None:
            next_cursor = self.stuck_cursor
        tickets = [self._view(key, with_handled=show_all) for key in page]
        return httpx.Response(200, json={"tickets": tickets, "next_cursor": next_cursor})

    def _detail(self, ticket_id: str) -> httpx.Response:
        if ticket_id not in self.tickets:
            return _error(404, "not_found", "No ticket with this id in your current ticket set.")
        return httpx.Response(200, json=self._view(ticket_id, with_handled=True))

    def _view(self, ticket_id: str, *, with_handled: bool) -> dict[str, Any]:
        view = dict(self.tickets[ticket_id])
        if with_handled:
            view["handled"] = self.handled.get(ticket_id)
        return view

    def _decide(self, ticket_id: str, action: str, content: bytes) -> httpx.Response:
        if ticket_id not in self.tickets:
            return _error(404, "not_found", "No ticket with this id in your current ticket set.")
        try:
            body = json.loads(content or b"null")
        except ValueError:
            return _error(400, "invalid_json", "Body is not valid JSON.")
        problems = validation_problems(action, body)
        if problems:
            return _error(422, "validation_failed", "A field is missing.", problems=problems)
        if ticket_id in self.handled:
            self.conflicts[ticket_id] += 1
            return _error(409, "already_handled", "This ticket was already handled.")
        self.handled[ticket_id] = {"action": action, **body}
        self.accepted_writes[ticket_id] += 1
        return httpx.Response(200, json={"ok": True, "id": ticket_id, "action": action})


def _error(
    status: int,
    code: str,
    message: str,
    *,
    headers: dict[str, str] | None = None,
    problems: list[str] | None = None,
) -> httpx.Response:
    body: dict[str, Any] = {"error": code, "message": message}
    if problems:
        body["problems"] = problems
    return httpx.Response(status, json=body, headers=headers)
