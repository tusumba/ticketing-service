import uuid

from pydantic import BaseModel

from app.models import RegistrationSource, RegistrationStatus, Visibility


class Participant(BaseModel):
    """Участник в списке организатора. У анонимного участника user_id равен null."""

    registration_id: uuid.UUID
    user_id: uuid.UUID | None
    status: RegistrationStatus
    visibility: Visibility
    source: RegistrationSource


class ParticipantPage(BaseModel):
    items: list[Participant]
    total: int
    page: int
    size: int
