"""Список участников мероприятия для организатора (#19052, требование #18100)."""

import datetime as dt
import uuid

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from tusumba_common import ApiError, EventPermissions
from tusumba_common.testing import make_token

from app.clients.permissions import get_permissions_client
from app.models import Registration, RegistrationSource, RegistrationStatus, Visibility


class FakePermissions:
    """Подменяет PermissionsClient: роли из словаря, неизвестное мероприятие - 404."""

    def __init__(self) -> None:
        self.roles: dict[uuid.UUID, dict[uuid.UUID, str]] = {}
        self.unavailable = False

    def add_event(self) -> uuid.UUID:
        event_id = uuid.uuid4()
        self.roles[event_id] = {}
        return event_id

    def grant(self, event_id: uuid.UUID, user_id: uuid.UUID, role: str) -> None:
        self.roles[event_id][user_id] = role

    async def event_permissions(self, event_id: uuid.UUID, user_id: uuid.UUID) -> EventPermissions:
        if self.unavailable:
            raise ApiError(
                503, "service_unavailable", "Сервис временно недоступен. Попробуйте позже."
            )
        if event_id not in self.roles:
            raise ApiError(404, "event_not_found", "Мероприятие недоступно.")
        role = self.roles[event_id].get(user_id)
        return EventPermissions(
            event_id=str(event_id), user_id=str(user_id), is_member=role is not None, role=role
        )


@pytest.fixture
def permissions(app: FastAPI) -> FakePermissions:
    fake = FakePermissions()
    app.dependency_overrides[get_permissions_client] = lambda: fake
    return fake


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def headers(private_key: str, user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(private_key, user_id=str(user_id))}"}


@pytest.fixture
def event_id(permissions: FakePermissions, user_id: uuid.UUID) -> uuid.UUID:
    """Мероприятие, где текущий пользователь - владелец."""
    event = permissions.add_event()
    permissions.grant(event, user_id, "owner")
    return event


async def add_participant(
    session: AsyncSession,
    event_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
    status: RegistrationStatus = RegistrationStatus.GOING,
    visibility: Visibility = Visibility.PUBLIC,
    source: RegistrationSource = RegistrationSource.FREE_SIGNUP,
    created_at: dt.datetime | None = None,
) -> Registration:
    registration = Registration(
        event_id=event_id,
        user_id=user_id or uuid.uuid4(),
        status=status,
        visibility=visibility,
        source=source,
        created_at=created_at or dt.datetime.now(dt.UTC),
    )
    session.add(registration)
    await session.flush()
    return registration


async def participants(
    client: httpx2.AsyncClient,
    event_id: uuid.UUID,
    headers: dict[str, str],
    **params: int,
) -> httpx2.Response:
    return await client.get(f"/v1/events/{event_id}/participants", params=params, headers=headers)


async def test_owner_sees_participants_in_signup_order(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    event_id: uuid.UUID,
    headers: dict[str, str],
) -> None:
    start = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)
    first = await add_participant(session, event_id, created_at=start)
    second = await add_participant(
        session,
        event_id,
        status=RegistrationStatus.INTERESTED,
        visibility=Visibility.FRIENDS_ONLY,
        created_at=start + dt.timedelta(hours=1),
    )
    third = await add_participant(
        session,
        event_id,
        source=RegistrationSource.TICKET,
        created_at=start + dt.timedelta(hours=2),
    )
    await add_participant(session, uuid.uuid4())

    response = await participants(client, event_id, headers)

    assert response.status_code == 200
    body = response.json()
    assert (body["total"], body["page"], body["size"]) == (3, 1, 20)
    assert body["items"] == [
        {
            "registration_id": str(row.id),
            "user_id": str(row.user_id),
            "status": row.status.value,
            "visibility": row.visibility.value,
            "source": row.source.value,
        }
        for row in (first, second, third)
    ]


async def test_admin_sees_participants(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    permissions: FakePermissions,
    event_id: uuid.UUID,
    private_key: str,
) -> None:
    admin = uuid.uuid4()
    permissions.grant(event_id, admin, "admin")
    await add_participant(session, event_id)
    headers = {"Authorization": f"Bearer {make_token(private_key, user_id=str(admin))}"}

    response = await participants(client, event_id, headers)

    assert response.status_code == 200
    assert response.json()["total"] == 1


async def test_anonymous_participant_without_user_id(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    event_id: uuid.UUID,
    headers: dict[str, str],
) -> None:
    anonymous = await add_participant(session, event_id, visibility=Visibility.ANONYMOUS)

    response = await participants(client, event_id, headers)

    assert response.json()["items"] == [
        {
            "registration_id": str(anonymous.id),
            "user_id": None,
            "status": "going",
            "visibility": "anonymous",
            "source": "free_signup",
        }
    ]
    assert str(anonymous.user_id) not in response.text


@pytest.mark.parametrize("role", ["editor", "scanner", None])
async def test_other_users_are_forbidden(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    permissions: FakePermissions,
    event_id: uuid.UUID,
    private_key: str,
    role: str | None,
) -> None:
    other = uuid.uuid4()
    if role is not None:
        permissions.grant(event_id, other, role)
    await add_participant(session, event_id)
    headers = {"Authorization": f"Bearer {make_token(private_key, user_id=str(other))}"}

    response = await participants(client, event_id, headers)

    assert response.status_code == 403
    assert response.json()["error"] == {"code": "forbidden", "message": "Недостаточно прав."}


async def test_pagination(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    event_id: uuid.UUID,
    headers: dict[str, str],
) -> None:
    start = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)
    rows = [
        await add_participant(session, event_id, created_at=start + dt.timedelta(minutes=i))
        for i in range(3)
    ]

    second = await participants(client, event_id, headers, page=2, size=2)

    assert second.status_code == 200
    assert second.json()["total"] == 3
    assert [item["registration_id"] for item in second.json()["items"]] == [str(rows[2].id)]


async def test_empty_list(
    client: httpx2.AsyncClient, event_id: uuid.UUID, headers: dict[str, str]
) -> None:
    response = await participants(client, event_id, headers)

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "page": 1, "size": 20}


async def test_unknown_event_is_not_found(
    client: httpx2.AsyncClient, permissions: FakePermissions, headers: dict[str, str]
) -> None:
    response = await participants(client, uuid.uuid4(), headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "event_not_found"


async def test_events_unavailable(
    client: httpx2.AsyncClient,
    permissions: FakePermissions,
    event_id: uuid.UUID,
    headers: dict[str, str],
) -> None:
    permissions.unavailable = True

    response = await participants(client, event_id, headers)

    assert response.status_code == 503


async def test_requires_token(client: httpx2.AsyncClient, event_id: uuid.UUID) -> None:
    response = await client.get(f"/v1/events/{event_id}/participants")

    assert response.status_code == 401


async def test_invalid_page_size(
    client: httpx2.AsyncClient, event_id: uuid.UUID, headers: dict[str, str]
) -> None:
    response = await participants(client, event_id, headers, size=101)

    assert response.status_code == 422
    assert [d["field"] for d in response.json()["error"]["details"]] == ["size"]
