"""Клиент events-service: мероприятие по GET /internal/events/{id} (OpenAPI Events)."""

import datetime as dt
import logging
import uuid
from typing import Annotated

import httpx
from fastapi import Depends, Request
from pydantic import BaseModel, ValidationError
from tusumba_common import ApiError, InternalClient

logger = logging.getLogger(__name__)

EVENT_NOT_FOUND = ("event_not_found", "Мероприятие недоступно.")
UNAVAILABLE = ("service_unavailable", "Сервис временно недоступен. Попробуйте позже.")

# «Сегодня» считается по Новосибирску, как в events-service. Летнего времени там нет с 2014 года.
NOVOSIBIRSK = dt.timezone(dt.timedelta(hours=7), "Asia/Novosibirsk")
FINISHED_STATUSES = frozenset({"held", "not_held"})


def today_in_novosibirsk() -> dt.date:
    return dt.datetime.now(NOVOSIBIRSK).date()


class EventInfo(BaseModel):
    """Поля EventInternal, которые нужны Ticketing."""

    id: uuid.UUID
    date: dt.date
    is_free: bool
    status: str

    def is_finished(self, today: dt.date) -> bool:
        """Мероприятие прошло: дата раньше сегодняшней или оно уже состоялось или не состоялось."""
        return self.date < today or self.status in FINISHED_STATUSES


class EventsClient:
    """events = EventsClient("http://events:8000"); event = await events.get_event(event_id)"""

    def __init__(self, base_url: str, *, client: httpx.AsyncClient | None = None) -> None:
        self._http = client or InternalClient(base_url=base_url)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_event(self, event_id: uuid.UUID) -> EventInfo:
        path = f"/internal/events/{event_id}"
        try:
            response = await self._http.get(path)
        except httpx.HTTPError:
            logger.warning("events-service не ответил на %s", path, exc_info=True)
            raise ApiError(503, *UNAVAILABLE) from None
        if response.status_code == 404:
            raise ApiError(404, *EVENT_NOT_FOUND)
        if response.status_code != 200:
            # 403 здесь значит неверный SERVICE_TOKEN: ошибка настройки, а не пользователя
            logger.error("events-service ответил %s на %s", response.status_code, path)
            raise ApiError(503, *UNAVAILABLE)
        try:
            return EventInfo.model_validate_json(response.content)
        except ValidationError:
            logger.error("events-service вернул неожиданный ответ на %s", path)
            raise ApiError(503, *UNAVAILABLE) from None


def get_events_client(request: Request) -> EventsClient:
    client: EventsClient = request.app.state.events_client
    return client


Events = Annotated[EventsClient, Depends(get_events_client)]
