import uuid

from fastapi import APIRouter, status

from app.api.deps import DbSession, Paging
from app.schemas.appointment import AppointmentOut
from app.schemas.common import Page, Phone
from app.schemas.patient import PatientCreate, PatientOut, PatientUpdate
from app.services import appointment_service, patient_service

router = APIRouter(tags=["patients"])


@router.get("/patients")
async def search_patients(
    db: DbSession,
    paging: Paging,
    hospital_id: uuid.UUID | None = None,
    phone: Phone | None = None,
    name: str | None = None,
) -> Page[PatientOut]:
    """`phone` is matched exactly after normalization; `name` by substring."""
    items, total = await patient_service.search_patients(
        db,
        hospital_id=hospital_id,
        phone=phone,
        name=name,
        limit=paging.limit,
        offset=paging.offset,
    )
    return Page(
        items=[PatientOut.model_validate(p) for p in items],
        total=total,
        limit=paging.limit,
        offset=paging.offset,
    )


@router.post("/patients", status_code=status.HTTP_201_CREATED)
async def create_patient(db: DbSession, body: PatientCreate) -> PatientOut:
    return PatientOut.model_validate(await patient_service.create_patient(db, body))


@router.get("/patients/{patient_id}")
async def get_patient(db: DbSession, patient_id: uuid.UUID) -> PatientOut:
    return PatientOut.model_validate(await patient_service.get_patient(db, patient_id))


@router.patch("/patients/{patient_id}")
async def update_patient(db: DbSession, patient_id: uuid.UUID, body: PatientUpdate) -> PatientOut:
    return PatientOut.model_validate(await patient_service.update_patient(db, patient_id, body))


@router.get("/patients/{patient_id}/appointments")
async def patient_appointments(
    db: DbSession, patient_id: uuid.UUID, paging: Paging
) -> Page[AppointmentOut]:
    await patient_service.get_patient(db, patient_id)
    items, total = await appointment_service.list_appointments(
        db, patient_id=patient_id, limit=paging.limit, offset=paging.offset
    )
    return Page(items=items, total=total, limit=paging.limit, offset=paging.offset)
