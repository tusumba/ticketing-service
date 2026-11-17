import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, Index, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RegistrationStatus(StrEnum):
    GOING = "going"
    INTERESTED = "interested"


class Visibility(StrEnum):
    PUBLIC = "public"
    FRIENDS_ONLY = "friends_only"
    ANONYMOUS = "anonymous"


class RegistrationSource(StrEnum):
    FREE_SIGNUP = "free_signup"
    TICKET = "ticket"


def _pg_enum(enum: type[StrEnum], name: str) -> Enum:
    return Enum(enum, name=name, values_callable=lambda e: [m.value for m in e])


class Registration(Base):
    __tablename__ = "registrations"
    __table_args__ = (
        UniqueConstraint("event_id", "user_id"),
        Index("ix_registrations_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID]
    user_id: Mapped[uuid.UUID]
    status: Mapped[RegistrationStatus] = mapped_column(
        _pg_enum(RegistrationStatus, "registration_status")
    )
    visibility: Mapped[Visibility] = mapped_column(_pg_enum(Visibility, "registration_visibility"))
    source: Mapped[RegistrationSource] = mapped_column(
        _pg_enum(RegistrationSource, "registration_source")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
