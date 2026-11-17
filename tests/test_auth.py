"""Проверка JWT, /internal и формата ошибок из tusumba-common. База для этих тестов не нужна."""

import uuid
from collections.abc import AsyncIterator

import httpx2
import pytest
from tusumba_common.testing import generate_keypair, make_token

from app.main import create_app
from app.settings import Settings
from tests.conftest import SERVICE_TOKEN

EVENT_ID = uuid.uuid4()
REGISTRATION_ENDPOINTS = [
    ("PUT", f"/v1/events/{EVENT_ID}/registration"),
    ("DELETE", f"/v1/events/{EVENT_ID}/registration"),
    ("GET", "/v1/me/registrations"),
]


@pytest.fixture
async def api() -> AsyncIterator[httpx2.AsyncClient]:
    settings = Settings(
        database_url="postgresql+asyncpg://test:test@localhost:5432/test",
        rabbitmq_url="amqp://guest:guest@localhost:5672/",
    )
    transport = httpx2.ASGITransport(app=create_app(settings))
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize(("method", "path"), REGISTRATION_ENDPOINTS)
async def test_registration_endpoints_require_token(
    api: httpx2.AsyncClient, method: str, path: str
) -> None:
    response = await api.request(method, path)
    assert response.status_code == 401
    assert response.json()["error"] == {
        "code": "not_authenticated",
        "message": "Требуется авторизация",
    }
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(
    ("expires_in", "typ", "code"),
    [
        (-10, "access", "token_expired"),
        (3600, "refresh", "invalid_token"),
    ],
)
async def test_expired_and_refresh_tokens_are_rejected(
    api: httpx2.AsyncClient, private_key: str, expires_in: int, typ: str, code: str
) -> None:
    token = make_token(private_key, user_id=str(uuid.uuid4()), expires_in=expires_in, typ=typ)
    response = await api.get("/v1/me/registrations", headers=bearer(token))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == code


async def test_token_signed_by_another_key_is_rejected(api: httpx2.AsyncClient) -> None:
    other_private_key, _ = generate_keypair()
    token = make_token(other_private_key, user_id=str(uuid.uuid4()))
    response = await api.get("/v1/me/registrations", headers=bearer(token))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


async def test_user_id_must_be_uuid(api: httpx2.AsyncClient, private_key: str) -> None:
    response = await api.get(
        "/v1/me/registrations", headers=bearer(make_token(private_key, user_id="user-1"))
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_unknown_path_uses_common_format(api: httpx2.AsyncClient) -> None:
    response = await api.get("/v1/unknown")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_internal_requires_service_token(api: httpx2.AsyncClient, private_key: str) -> None:
    for headers in ({}, {"X-Service-Token": "wrong"}, bearer(make_token(private_key))):
        response = await api.get("/internal/example/ping", headers=headers)
        assert response.status_code == 403, headers
        assert response.json()["error"]["code"] == "forbidden"

    response = await api.get("/internal/example/ping", headers={"X-Service-Token": SERVICE_TOKEN})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
