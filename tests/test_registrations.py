"""Запись на бесплатное мероприятие, отмена и «мои записи» (#19051, требования #18115, #18116)."""

import datetime as dt
import uuid
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from tusumba_common import ApiError
from tusumba_common.testing import make_token
from tusumba_contracts import RegistrationChanged

from app.clients.events import (
    EVENT_NOT_FOUND,
    EventInfo,
    get_events_client,
    today_in_novosibirsk,
)
from app.models import (
    OutboxMessage,
    Registration,
    RegistrationSource,
    RegistrationStatus,
    Visibility,
)

TODAY = dt.date(2026, 11, 11)


class FakeEvents:
    """Подменяет events-service: мероприятия из словаря, неизвестное - 404 event_not_found."""

    def __init__(self) -> None:
        self.events: dict[uuid.UUID, EventInfo] = {}

    def add(
        self, *, is_free: bool = True, date: dt.date = TODAY, status: str = "confirmed"
    ) -> uuid.UUID:
        event_id = uuid.uuid4()
        self.events[event_id] = EventInfo(id=event_id, date=date, is_free=is_free, status=status)
        return event_id

    async def get_event(self, event_id: uuid.UUID) -> EventInfo:
        try:
            return self.events[event_id]
        except KeyError:
            raise ApiError(404, *EVENT_NOT_FOUND) from None


@pytest.fixture
def events(app: FastAPI) -> FakeEvents:
    fake = FakeEvents()
    app.dependency_overrides[get_events_client] = lambda: fake
    app.dependency_overrides[today_in_novosibirsk] = lambda: TODAY
    return fake


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


def auth(private_key: str, user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(private_key, user_id=str(user_id))}"}


@pytest.fixture
def headers(private_key: str, user_id: uuid.UUID) -> dict[str, str]:
    return auth(private_key, user_id)


async def register(
    client: httpx2.AsyncClient, event_id: uuid.UUID, headers: dict[str, str], **body: str
) -> httpx2.Response:
    return await client.put(f"/v1/events/{event_id}/registration", json=body, headers=headers)


async def cancel(
    client: httpx2.AsyncClient, event_id: uuid.UUID, headers: dict[str, str]
) -> httpx2.Response:
    return await client.delete(f"/v1/events/{event_id}/registration", headers=headers)


async def pop_published(session: AsyncSession) -> list[dict[str, Any]]:
    """Payload событий RegistrationChanged из outbox; outbox очищается для следующей проверки."""
    rows = await session.scalars(
        select(OutboxMessage).where(OutboxMessage.routing_key == RegistrationChanged.routing_key)
    )
    payloads = [row.payload["payload"] for row in rows]
    await session.execute(delete(OutboxMessage))
    return payloads


async def count_registrations(session: AsyncSession, event_id: uuid.UUID) -> int:
    total = await session.scalar(
        select(func.count()).select_from(Registration).where(Registration.event_id == event_id)
    )
    return total or 0


async def add_registration(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    event_id: uuid.UUID | None = None,
    source: RegistrationSource = RegistrationSource.FREE_SIGNUP,
    created_at: dt.datetime | None = None,
) -> Registration:
    registration = Registration(
        event_id=event_id or uuid.uuid4(),
        user_id=user_id,
        status=RegistrationStatus.GOING,
        visibility=Visibility.PUBLIC,
        source=source,
        created_at=created_at or dt.datetime.now(dt.UTC),
    )
    session.add(registration)
    await session.flush()
    return registration


async def test_register_creates_public_registration(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    events: FakeEvents,
    headers: dict[str, str],
    user_id: uuid.UUID,
) -> None:
    event_id = events.add()

    response = await register(client, event_id, headers, status="going")

    assert response.status_code == 201
    body = response.json()
    assert body["event_id"] == str(event_id)
    assert (body["status"], body["visibility"], body["source"]) == (
        "going",
        "public",
        "free_signup",
    )
    assert set(body) == {"id", "event_id", "status", "visibility", "source", "created_at"}
    assert await pop_published(session) == [
        {
            "registration_id": body["id"],
            "event_id": str(event_id),
            "user_id": str(user_id),
            "action": "created",
            "status": "going",
            "visibility": "public",
            "source": "free_signup",
        }
    ]


async def test_repeat_changes_status_instead_of_duplicate(
    client: httpx2.AsyncClient, session: AsyncSession, events: FakeEvents, headers: dict[str, str]
) -> None:
    event_id = events.add()
    created = (await register(client, event_id, headers, status="going")).json()
    await pop_published(session)

    response = await register(client, event_id, headers, status="interested")

    assert response.status_code == 200
    assert response.json() == {**created, "status": "interested"}
    assert await count_registrations(session, event_id) == 1
    published = await pop_published(session)
    assert [(p["action"], p["status"]) for p in published] == [("updated", "interested")]


async def test_visibility_changes_only_when_passed(
    client: httpx2.AsyncClient, events: FakeEvents, headers: dict[str, str]
) -> None:
    event_id = events.add()

    anonymous = await register(client, event_id, headers, status="going", visibility="anonymous")
    kept = await register(client, event_id, headers, status="interested")
    friends = await register(
        client, event_id, headers, status="interested", visibility="friends_only"
    )

    assert anonymous.json()["visibility"] == "anonymous"
    assert kept.json()["visibility"] == "anonymous"
    assert friends.json()["visibility"] == "friends_only"


async def test_same_choice_again_changes_nothing(
    client: httpx2.AsyncClient, session: AsyncSession, events: FakeEvents, headers: dict[str, str]
) -> None:
    event_id = events.add()
    created = (await register(client, event_id, headers, status="going")).json()
    await pop_published(session)

    response = await register(client, event_id, headers, status="going", visibility="public")

    assert response.status_code == 200
    assert response.json() == created
    assert await pop_published(session) == []


async def test_users_register_separately(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    events: FakeEvents,
    headers: dict[str, str],
    private_key: str,
) -> None:
    event_id = events.add()

    first = await register(client, event_id, headers, status="going")
    second = await register(client, event_id, auth(private_key, uuid.uuid4()), status="going")

    assert (first.status_code, second.status_code) == (201, 201)
    assert first.json()["id"] != second.json()["id"]
    assert await count_registrations(session, event_id) == 2


async def test_one_registration_per_event_and_user_in_database(
    session: AsyncSession, user_id: uuid.UUID
) -> None:
    existing = await add_registration(session, user_id=user_id)
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await add_registration(session, user_id=user_id, event_id=existing.event_id)


async def test_cancel_deletes_registration(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    events: FakeEvents,
    headers: dict[str, str],
    user_id: uuid.UUID,
) -> None:
    event_id = events.add()
    created = (await register(client, event_id, headers, status="interested")).json()
    await pop_published(session)

    response = await cancel(client, event_id, headers)

    assert response.status_code == 204
    assert response.content == b""
    assert await count_registrations(session, event_id) == 0
    assert await pop_published(session) == [
        {
            "registration_id": created["id"],
            "event_id": str(event_id),
            "user_id": str(user_id),
            "action": "deleted",
            "status": None,
            "visibility": None,
            "source": "free_signup",
        }
    ]
    assert (await client.get("/v1/me/registrations", headers=headers)).json()["items"] == []


async def test_register_again_after_cancel(
    client: httpx2.AsyncClient, events: FakeEvents, headers: dict[str, str]
) -> None:
    event_id = events.add()
    await register(client, event_id, headers, status="going")
    await cancel(client, event_id, headers)

    response = await register(client, event_id, headers, status="going")

    assert response.status_code == 201


async def test_cancel_without_registration_is_not_found(
    client: httpx2.AsyncClient, events: FakeEvents, headers: dict[str, str]
) -> None:
    response = await cancel(client, events.add(), headers)

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "registration_not_found",
        "message": "Вы не записаны на это мероприятие.",
    }


async def test_cancel_only_own_registration(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    events: FakeEvents,
    headers: dict[str, str],
    private_key: str,
) -> None:
    event_id = events.add()
    await register(client, event_id, headers, status="going")

    response = await cancel(client, event_id, auth(private_key, uuid.uuid4()))

    assert response.status_code == 404
    assert await count_registrations(session, event_id) == 1


async def test_registration_from_ticket_cannot_be_cancelled(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    events: FakeEvents,
    headers: dict[str, str],
    user_id: uuid.UUID,
) -> None:
    event_id = events.add(is_free=False)
    await add_registration(
        session, user_id=user_id, event_id=event_id, source=RegistrationSource.TICKET
    )

    response = await cancel(client, event_id, headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "registration_from_ticket"
    assert await count_registrations(session, event_id) == 1


async def test_paid_event_requires_ticket(
    client: httpx2.AsyncClient, session: AsyncSession, events: FakeEvents, headers: dict[str, str]
) -> None:
    event_id = events.add(is_free=False)

    response = await register(client, event_id, headers, status="going")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "event_is_paid"
    assert await count_registrations(session, event_id) == 0


@pytest.mark.parametrize(
    ("date", "status"),
    [
        (TODAY - dt.timedelta(days=1), "confirmed"),
        (TODAY, "held"),
        (TODAY, "not_held"),
    ],
)
async def test_finished_event_closes_registration(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    events: FakeEvents,
    headers: dict[str, str],
    date: dt.date,
    status: str,
) -> None:
    event_id = events.add(date=date, status=status)

    response = await register(client, event_id, headers, status="going")

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "event_finished",
        "message": "Запись на мероприятие закрыта.",
    }
    assert await count_registrations(session, event_id) == 0


@pytest.mark.parametrize("status", ["not_confirmed", "confirmed"])
async def test_event_today_is_open(
    client: httpx2.AsyncClient, events: FakeEvents, headers: dict[str, str], status: str
) -> None:
    response = await register(
        client, events.add(date=TODAY, status=status), headers, status="going"
    )
    assert response.status_code == 201


async def test_cancel_on_finished_event_is_rejected(
    client: httpx2.AsyncClient, session: AsyncSession, events: FakeEvents, headers: dict[str, str]
) -> None:
    event_id = events.add()
    await register(client, event_id, headers, status="going")
    events.events[event_id] = events.events[event_id].model_copy(update={"status": "held"})

    response = await cancel(client, event_id, headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "event_finished"
    assert await count_registrations(session, event_id) == 1


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
async def test_unknown_event_is_not_found(
    client: httpx2.AsyncClient, events: FakeEvents, headers: dict[str, str], method: str
) -> None:
    response = await client.request(
        method,
        f"/v1/events/{uuid.uuid4()}/registration",
        json={"status": "going"} if method == "PUT" else None,
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "event_not_found",
        "message": "Мероприятие недоступно.",
    }


async def test_my_registrations_newest_first_with_pagination(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    events: FakeEvents,
    headers: dict[str, str],
    user_id: uuid.UUID,
) -> None:
    start = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)
    oldest, middle, newest = [
        await add_registration(
            session,
            user_id=user_id,
            source=source,
            created_at=start + dt.timedelta(hours=hours),
        )
        for hours, source in [
            (0, RegistrationSource.FREE_SIGNUP),
            (1, RegistrationSource.TICKET),
            (2, RegistrationSource.FREE_SIGNUP),
        ]
    ]
    await add_registration(session, user_id=uuid.uuid4())

    first = await client.get("/v1/me/registrations", params={"size": 2}, headers=headers)
    second = await client.get(
        "/v1/me/registrations", params={"page": 2, "size": 2}, headers=headers
    )

    assert first.status_code == 200
    assert {key: first.json()[key] for key in ("total", "page", "size")} == {
        "total": 3,
        "page": 1,
        "size": 2,
    }
    assert [item["id"] for item in first.json()["items"]] == [str(newest.id), str(middle.id)]
    assert first.json()["items"][1]["source"] == "ticket"
    assert [item["id"] for item in second.json()["items"]] == [str(oldest.id)]


async def test_my_registrations_empty(
    client: httpx2.AsyncClient, events: FakeEvents, headers: dict[str, str]
) -> None:
    response = await client.get("/v1/me/registrations", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "page": 1, "size": 20}


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"status": "maybe"}, "status"),
        ({}, "status"),
        ({"status": "going", "visibility": "secret"}, "visibility"),
    ],
)
async def test_invalid_registration_body(
    client: httpx2.AsyncClient,
    events: FakeEvents,
    headers: dict[str, str],
    body: dict[str, str],
    field: str,
) -> None:
    response = await client.put(
        f"/v1/events/{events.add()}/registration", json=body, headers=headers
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert [detail["field"] for detail in error["details"]] == [field]


async def test_invalid_event_id_and_page_size(
    client: httpx2.AsyncClient, events: FakeEvents, headers: dict[str, str]
) -> None:
    bad_id = await client.put(
        "/v1/events/abc/registration", json={"status": "going"}, headers=headers
    )
    bad_size = await client.get("/v1/me/registrations", params={"size": 101}, headers=headers)

    assert bad_id.status_code == 422
    assert [d["field"] for d in bad_id.json()["error"]["details"]] == ["id"]
    assert bad_size.status_code == 422
    assert [d["field"] for d in bad_size.json()["error"]["details"]] == ["size"]
