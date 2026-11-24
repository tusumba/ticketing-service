from fastapi import APIRouter

from app.api.v1 import participants, registrations

router = APIRouter(prefix="/v1")
router.include_router(registrations.router)
router.include_router(participants.router)
