from fastapi import APIRouter, Depends

from app.api.deps import require_staff
from app.api.v1 import health

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)

protected = APIRouter(dependencies=[Depends(require_staff)])

api_router.include_router(protected)
