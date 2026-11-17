import uuid
from typing import Annotated

from fastapi import Depends
from tusumba_common import ApiError, CurrentUser, get_current_user


async def current_user_id(user: Annotated[CurrentUser, Depends(get_current_user)]) -> uuid.UUID:
    """id пользователя из access-токена: Identity выдаёт UUID, иначе токен недействителен."""
    try:
        return uuid.UUID(user.id)
    except ValueError:
        raise ApiError(
            401, "invalid_token", "Недействительный токен", headers={"WWW-Authenticate": "Bearer"}
        ) from None


CurrentUserId = Annotated[uuid.UUID, Depends(current_user_id)]
