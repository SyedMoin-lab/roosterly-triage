import httpx

from tests.fakes.clock import FakeClock
from tests.fakes.helpdesk import API_KEY, BASE_URL, CANDIDATE_EMAIL, FakeHelpdesk, make_ticket

HEADERS = {"Authorization": f"Bearer {API_KEY}", "X-Candidate-Email": CANDIDATE_EMAIL}
REPLY_BODY = {
    "language": "nl",
    "category": "question",
    "priority": "P4",
    "reason": "FAQ F01.",
    "draft_reply": "Hoi",
}


def fake_and_http() -> tuple[FakeHelpdesk, httpx.Client]:
    fake = FakeHelpdesk([make_ticket(1), make_ticket(2)], clock=FakeClock())
    return fake, httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(fake.handle))


def test_the_fake_answers_a_second_decision_with_a_409() -> None:
    fake, http = fake_and_http()
    first = http.post("/tickets/T001/reply", json=REPLY_BODY, headers=HEADERS)
    second = http.post("/tickets/T001/reply", json=REPLY_BODY, headers=HEADERS)
    assert (first.status_code, second.status_code) == (200, 409)
    assert second.json()["error"] == "already_handled"
    assert (fake.accepted_writes["T001"], fake.conflicts["T001"]) == (1, 1)


def test_the_fake_rate_limits_more_than_five_requests_a_second() -> None:
    fake, http = fake_and_http()
    statuses = [http.get("/status", headers=HEADERS).status_code for _ in range(7)]
    assert statuses.count(429) == 2
    assert fake.statuses[429] == 2


def test_the_fake_rejects_missing_credentials() -> None:
    _, http = fake_and_http()
    assert http.get("/status").status_code == 401
    assert http.get("/status", headers={"Authorization": f"Bearer {API_KEY}"}).status_code == 400


def test_the_fake_validates_decision_bodies() -> None:
    _, http = fake_and_http()
    response = http.post("/tickets/T002/handoff", json=REPLY_BODY, headers=HEADERS)
    assert response.status_code == 422
    assert "handoff_note is required for a handoff" in response.json()["problems"]


def test_the_fake_reset_reopens_every_ticket() -> None:
    fake, http = fake_and_http()
    http.post("/tickets/T001/reply", json=REPLY_BODY, headers=HEADERS)
    http.post("/practice/reset", headers=HEADERS)
    assert fake.handled == {}
