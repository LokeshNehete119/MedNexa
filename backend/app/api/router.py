from fastapi import APIRouter, Depends

from app.api.deps import require_staff
from app.api.v1 import doctors, health, hospitals

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)

# include_router copies routes, so every protected module is added before `protected`
# itself is included below.
protected = APIRouter(dependencies=[Depends(require_staff)])
protected.include_router(hospitals.router)
protected.include_router(doctors.router)

api_router.include_router(protected)
