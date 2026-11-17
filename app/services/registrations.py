"""Запись на бесплатное мероприятие, отмена записи и «мои записи» (#18115, #18116)."""

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import Boolean, func, literal_column, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from tusumba_common import ApiError
from tusumba_contracts import RegistrationChanged

from app.clients.events import EventsClient
from app.events import enqueue_event
from app.models import Registration, RegistrationSource, Visibility
from app.schemas import registrations as schemas

EVENT_IS_PAID = (409, "event_is_paid", "Мероприятие платное, чтобы пойти, купите билет.")
EVENT_FINISHED = (409, "event_finished", "Запись на мероприятие закрыта.")
REGISTRATION_NOT_FOUND = (404, "registration_not_found", "Вы не записаны на это мероприятие.")
REGISTRATION_FROM_TICKET = (
    409,
    "registration_from_ticket",
    "Запись по купленному билету отменить нельзя.",
)


@dataclass(frozen=True)
class SaveResult:
    registration: schemas.Registration
    created: bool


async def register(
    session: AsyncSession,
    events: EventsClient,
    *,
    event_id: uuid.UUID,
    user_id: uuid.UUID,
    request: schemas.RegistrationRequest,
    today: dt.date,
) -> SaveResult:
    """Создаёт запись или меняет статус и видимость существующей: одна запись на пару
    «мероприятие, пользователь», повторный запрос дубль не создаёт."""
    event = await events.get_event(event_id)
    if not event.is_free:
        raise ApiError(*EVENT_IS_PAID)
    if event.is_finished(today):
        raise ApiError(*EVENT_FINISHED)

    insert_stmt = insert(Registration).values(
        id=uuid.uuid4(),
        event_id=event_id,
        user_id=user_id,
        status=request.status,
        visibility=request.visibility or Visibility.PUBLIC,
        source=RegistrationSource.FREE_SIGNUP,
    )
    changes: dict[str, Any] = {"status": insert_stmt.excluded.status}
    if request.visibility is not None:
        changes["visibility"] = insert_stmt.excluded.visibility
    upsert = (
        insert_stmt.on_conflict_do_update(
            index_elements=[Registration.event_id, Registration.user_id],
            set_=changes,
            # Повтор с теми же значениями строку не трогает: RETURNING пустой, событие не нужно.
            where=or_(*(getattr(Registration, field) != value for field, value in changes.items())),
        )
        # xmax = 0 только у строки, которую вставил этот INSERT, а не обновил ON CONFLICT.
        .returning(Registration, literal_column("xmax = 0", Boolean).label("created"))
        .execution_options(populate_existing=True)
    )
    row = (await session.execute(upsert)).one_or_none()
    if row is None:
        unchanged = (
            await session.scalars(
                select(Registration).where(
                    Registration.event_id == event_id, Registration.user_id == user_id
                )
            )
        ).one()
        await session.commit()
        return SaveResult(schemas.Registration.model_validate(unchanged), created=False)

    registration, created = row
    enqueue_event(session, _changed(registration, "created" if created else "updated"))
    await session.commit()
    return SaveResult(schemas.Registration.model_validate(registration), created=created)


async def cancel(
    session: AsyncSession,
    events: EventsClient,
    *,
    event_id: uuid.UUID,
    user_id: uuid.UUID,
    today: dt.date,
) -> None:
    """Удаляет запись. На прошедшее мероприятие и по купленному билету запись не отменяется."""
    event = await events.get_event(event_id)
    if event.is_finished(today):
        raise ApiError(*EVENT_FINISHED)
    registration = await session.scalar(
        select(Registration)
        .where(Registration.event_id == event_id, Registration.user_id == user_id)
        .with_for_update()
    )
    if registration is None:
        raise ApiError(*REGISTRATION_NOT_FOUND)
    if registration.source == RegistrationSource.TICKET:
        raise ApiError(*REGISTRATION_FROM_TICKET)
    await session.delete(registration)
    enqueue_event(session, _changed(registration, "deleted"))
    await session.commit()


async def list_mine(
    session: AsyncSession, user_id: uuid.UUID, *, page: int, size: int
) -> schemas.RegistrationPage:
    """Записи пользователя, новые первыми."""
    mine = Registration.user_id == user_id
    total = await session.scalar(select(func.count()).select_from(Registration).where(mine))
    rows = await session.scalars(
        select(Registration)
        .where(mine)
        .order_by(Registration.created_at.desc(), Registration.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    return schemas.RegistrationPage(
        items=[schemas.Registration.model_validate(row) for row in rows],
        total=total or 0,
        page=page,
        size=size,
    )


def _changed(
    registration: Registration, action: Literal["created", "updated", "deleted"]
) -> RegistrationChanged:
    deleted = action == "deleted"
    return RegistrationChanged.model_validate(
        {
            "registration_id": registration.id,
            "event_id": registration.event_id,
            "user_id": registration.user_id,
            "action": action,
            "status": None if deleted else registration.status.value,
            "visibility": None if deleted else registration.visibility.value,
            "source": registration.source.value,
        }
    )
