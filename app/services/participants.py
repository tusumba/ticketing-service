"""Список участников мероприятия для организатора (#18100)."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tusumba_common import ApiError, PermissionsClient

from app.models import Registration, Visibility
from app.schemas.participants import Participant, ParticipantPage

ORGANIZER_ROLES = ("owner", "admin")
FORBIDDEN = (403, "forbidden", "Недостаточно прав.")


async def list_participants(
    session: AsyncSession,
    permissions: PermissionsClient,
    *,
    event_id: uuid.UUID,
    user_id: uuid.UUID,
    page: int,
    size: int,
) -> ParticipantPage:
    """Бесплатные записи и записи по купленным билетам в порядке записи.

    Список видят владелец и администратор мероприятия. Нет мероприятия - 404 event_not_found
    от events-service, Events недоступен - 503 (PermissionsClient).
    """
    if not (await permissions.event_permissions(event_id, user_id)).has_role(*ORGANIZER_ROLES):
        raise ApiError(*FORBIDDEN)

    of_event = Registration.event_id == event_id
    total = await session.scalar(select(func.count()).select_from(Registration).where(of_event))
    rows = await session.scalars(
        select(Registration)
        .where(of_event)
        .order_by(Registration.created_at, Registration.id)
        .offset((page - 1) * size)
        .limit(size)
    )
    return ParticipantPage(
        items=[_participant(row) for row in rows], total=total or 0, page=page, size=size
    )


def _participant(registration: Registration) -> Participant:
    anonymous = registration.visibility == Visibility.ANONYMOUS
    return Participant(
        registration_id=registration.id,
        # Имя клиент получает у Identity по user_id, поэтому у анонимного участника его нет.
        user_id=None if anonymous else registration.user_id,
        status=registration.status,
        visibility=registration.visibility,
        source=registration.source,
    )
