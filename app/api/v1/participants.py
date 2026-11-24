"""Участники мероприятия: GET /v1/events/{id}/participants."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query

from app.api.deps import CurrentUserId
from app.clients.permissions import Permissions
from app.db import Session
from app.schemas.participants import ParticipantPage
from app.services import participants

router = APIRouter(tags=["participants"])


@router.get(
    "/events/{id}/participants",
    operation_id="listParticipants",
    summary="Список участников мероприятия",
)
async def list_participants(
    user_id: CurrentUserId,
    event_id: Annotated[uuid.UUID, Path(alias="id", description="Идентификатор мероприятия")],
    session: Session,
    permissions: Permissions,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ParticipantPage:
    """Владельцу и администратору мероприятия, остальным 403. Анонимный участник - без user_id."""
    return await participants.list_participants(
        session, permissions, event_id=event_id, user_id=user_id, page=page, size=size
    )
