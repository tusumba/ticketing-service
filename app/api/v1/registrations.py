"""Записи на мероприятия: PUT и DELETE /v1/events/{id}/registration, GET /v1/me/registrations."""

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status

from app.api.deps import CurrentUserId
from app.clients.events import Events, today_in_novosibirsk
from app.db import Session
from app.schemas.registrations import Registration, RegistrationPage, RegistrationRequest
from app.services import registrations

router = APIRouter(tags=["registrations"])

EventId = Annotated[uuid.UUID, Path(alias="id", description="Идентификатор мероприятия")]
Today = Annotated[dt.date, Depends(today_in_novosibirsk)]


@router.put(
    "/events/{id}/registration",
    operation_id="registerForEvent",
    summary="Записаться на бесплатное мероприятие или изменить запись",
    responses={status.HTTP_201_CREATED: {"model": Registration, "description": "Запись создана"}},
)
async def register_for_event(
    user_id: CurrentUserId,
    event_id: EventId,
    body: RegistrationRequest,
    response: Response,
    session: Session,
    events: Events,
    today: Today,
) -> Registration:
    """«Пойду» или «Интересно». Повторный запрос меняет статус и видимость записи, ответ 200."""
    result = await registrations.register(
        session, events, event_id=event_id, user_id=user_id, request=body, today=today
    )
    if result.created:
        response.status_code = status.HTTP_201_CREATED
    return result.registration


@router.delete(
    "/events/{id}/registration",
    operation_id="cancelRegistration",
    summary="Отменить запись на мероприятие",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_registration(
    user_id: CurrentUserId,
    event_id: EventId,
    session: Session,
    events: Events,
    today: Today,
) -> None:
    await registrations.cancel(session, events, event_id=event_id, user_id=user_id, today=today)


@router.get(
    "/me/registrations",
    operation_id="listMyRegistrations",
    summary="Мои записи на мероприятия",
)
async def list_my_registrations(
    user_id: CurrentUserId,
    session: Session,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> RegistrationPage:
    return await registrations.list_mine(session, user_id, page=page, size=size)
