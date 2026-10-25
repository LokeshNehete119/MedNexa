"""Staff-facing appointment routes (admin dashboard).

The AI agent does not use these: it calls the service contract directly, where
cancel/reschedule enforce caller phone ownership.
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import DbSession, Paging
from app.models import AppointmentStatus, BookingSource
from app.schemas.appointment import (
    AppointmentOut,
    BookingConfirmation,
    BookingRequest,
    CancelRequest,
    RescheduleRequest,
)
from app.schemas.common import Page
from app.services import appointment_service

router = APIRouter(tags=["appointments"])


@router.get("/appointments")
async def list_appointments(
    db: DbSession,
    paging: Paging,
    hospital_id: uuid.UUID | None = None,
    doctor_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    on: Annotated[date | None, Query(alias="date")] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status: AppointmentStatus | None = None,
) -> Page[AppointmentOut]:
    items, total = await appointment_service.list_appointments(
        db,
        hospital_id=hospital_id,
        doctor_id=doctor_id,
        patient_id=patient_id,
        on=on,
        date_from=date_from,
        date_to=date_to,
        status=status,
        limit=paging.limit,
        offset=paging.offset,
    )
    return Page(items=items, total=total, limit=paging.limit, offset=paging.offset)


@router.post("/appointments", status_code=status.HTTP_201_CREATED)
async def book_appointment(db: DbSession, body: BookingRequest) -> BookingConfirmation:
    """Book on behalf of a patient. `booking_source` defaults to DASHBOARD here."""
    if "booking_source" not in body.model_fields_set:
        body.booking_source = BookingSource.DASHBOARD
    return await appointment_service.book_appointment(db, body)


@router.get("/appointments/{appointment_id}")
async def get_appointment(db: DbSession, appointment_id: uuid.UUID) -> AppointmentOut:
    return await appointment_service.get_appointment(db, appointment_id)


@router.post("/appointments/{appointment_id}/cancel")
async def cancel_appointment(
    db: DbSession, appointment_id: uuid.UUID, body: CancelRequest
) -> AppointmentOut:
    return await appointment_service.cancel_appointment_by_staff(db, appointment_id, body.reason)


@router.post("/appointments/{appointment_id}/reschedule")
async def reschedule_appointment(
    db: DbSession, appointment_id: uuid.UUID, body: RescheduleRequest
) -> BookingConfirmation:
    return await appointment_service.reschedule_appointment_by_staff(
        db, appointment_id, body.new_date, body.new_time
    )
