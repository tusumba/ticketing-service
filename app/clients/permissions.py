"""Клиент прав на мероприятие из tusumba-common: роль пользователя в команде у events-service."""

from typing import Annotated, cast

from fastapi import Depends, Request
from redis.asyncio import Redis
from tusumba_common import PermissionsClient
from tusumba_common.permissions import AsyncRedis

from app.settings import Settings


def create_redis(settings: Settings) -> Redis | None:
    if settings.redis_url is None or not settings.redis_url.get_secret_value():
        return None
    return Redis.from_url(settings.redis_url.get_secret_value(), decode_responses=True)


def create_permissions_client(settings: Settings, redis: Redis | None) -> PermissionsClient:
    # В стабах redis-py get/set/delete объявлены синхронными, хотя в redis.asyncio это корутины,
    # поэтому mypy не сопоставляет Redis с протоколом AsyncRedis.
    return PermissionsClient(settings.events_url, cast(AsyncRedis | None, redis))


def get_permissions_client(request: Request) -> PermissionsClient:
    client: PermissionsClient = request.app.state.permissions_client
    return client


Permissions = Annotated[PermissionsClient, Depends(get_permissions_client)]
