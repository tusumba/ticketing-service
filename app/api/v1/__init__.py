from fastapi import APIRouter

from app.api.v1 import registrations

router = APIRouter(prefix="/v1")
router.include_router(registrations.router)
