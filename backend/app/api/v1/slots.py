import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.schemas.slot import DoctorSlotOut, SlotOut
from app.services import slot_service

router = APIRouter(tags=["slots"])


@router.get("/doctors/{doctor_id}/slots")
async def doctor_slots(
    db: DbSession, doctor_id: uuid.UUID, on: Annotated[date, Query(alias="date")]
) -> list[SlotOut]:
    return await slot_service.get_available_slots(db, doctor_id, on)


@router.get("/slots/next-available")
async def next_available(
    db: DbSession,
    hospital_id: uuid.UUID,
    speciality: Annotated[str, Query(min_length=1)],
    from_date: Annotated[date | None, Query(alias="from")] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 5,
) -> list[DoctorSlotOut]:
    """Earliest free slots across doctors whose speciality or department matches."""
    return await slot_service.find_next_available(db, hospital_id, speciality, from_date, limit)
