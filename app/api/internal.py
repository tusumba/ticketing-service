"""Пути /internal для других сервисов: только с верным X-Service-Token, иначе 403."""

from fastapi import APIRouter, Depends
from tusumba_common import require_service

from app.api.health import Health

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(require_service)])


@router.get("/example/ping")
async def example_ping() -> Health:
    return Health()
