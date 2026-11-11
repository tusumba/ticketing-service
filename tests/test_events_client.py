"""Клиент events-service: GET /internal/events/{id} с сервисным токеном (OpenAPI Events)."""

import datetime as dt
import json
import uuid
from collections.abc import Callable

import httpx
import pytest
from tusumba_common import ApiError, InternalClient

from app.clients.events import EventInfo, EventsClient
from tests.conftest import SERVICE_TOKEN

EVENT_ID = uuid.uuid4()
EVENT = {
    "id": str(EVENT_ID),
    "title": "Лекция",
    "date": "2026-11-20",
    "place_address": "Новосибирск, ул. Пирогова, 1",
    "is_free": True,
    "status": "confirmed",
    "club_id": None,
    "created_by_user_id": str(uuid.uuid4()),
    "current_version_id": str(uuid.uuid4()),
}

Handler = Callable[[httpx.Request], httpx.Response]


def events_client(handler: Handler) -> EventsClient:
    http = InternalClient(base_url="http://events", transport=httpx.MockTransport(handler))
    return EventsClient("http://events", client=http)


async def test_returns_event_and_sends_service_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=EVENT)

    event = await events_client(handler).get_event(EVENT_ID)

    assert event == EventInfo(
        id=EVENT_ID, date=dt.date(2026, 11, 20), is_free=True, status="confirmed"
    )
    assert requests[0].url.path == f"/internal/events/{EVENT_ID}"
    assert requests[0].headers["X-Service-Token"] == SERVICE_TOKEN


async def test_missing_event_is_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        error = {"code": "event_not_found", "message": "Мероприятие недоступно."}
        return httpx.Response(404, json={"error": error})

    with pytest.raises(ApiError) as raised:
        await events_client(handler).get_event(EVENT_ID)

    assert (raised.value.status_code, raised.value.code) == (404, "event_not_found")
    assert raised.value.message == "Мероприятие недоступно."


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(403, json={"error": {"code": "forbidden", "message": "Доступ запрещён"}}),
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, content=json.dumps({**EVENT, "is_free": None}).encode()),
    ],
)
async def test_unexpected_answer_means_service_unavailable(response: httpx.Response) -> None:
    with pytest.raises(ApiError) as raised:
        await events_client(lambda request: response).get_event(EVENT_ID)

    assert (raised.value.status_code, raised.value.code) == (503, "service_unavailable")


async def test_events_down_means_service_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(ApiError) as raised:
        await events_client(handler).get_event(EVENT_ID)

    assert (raised.value.status_code, raised.value.code) == (503, "service_unavailable")


@pytest.mark.parametrize(
    ("date", "status", "finished"),
    [
        (dt.date(2026, 11, 12), "confirmed", False),
        (dt.date(2026, 11, 11), "not_confirmed", False),
        (dt.date(2026, 11, 10), "confirmed", True),
        (dt.date(2026, 11, 12), "held", True),
        (dt.date(2026, 11, 12), "not_held", True),
    ],
)
def test_event_is_finished(date: dt.date, status: str, finished: bool) -> None:
    event = EventInfo(id=EVENT_ID, date=date, is_free=True, status=status)
    assert event.is_finished(today=dt.date(2026, 11, 11)) is finished
