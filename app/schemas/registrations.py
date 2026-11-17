import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import RegistrationSource, RegistrationStatus, Visibility


class RegistrationRequest(BaseModel):
    """Если visibility не передана, новая запись получает public, у существующей она не меняется."""

    status: RegistrationStatus
    visibility: Visibility | None = None


class Registration(BaseModel):
    """Запись пользователя на мероприятие."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    status: RegistrationStatus
    visibility: Visibility
    source: RegistrationSource
    created_at: datetime


class RegistrationPage(BaseModel):
    items: list[Registration]
    total: int
    page: int
    size: int
