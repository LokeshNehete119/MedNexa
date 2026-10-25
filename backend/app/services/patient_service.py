import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Conflict, NotFound
from app.core.normalize import normalize_name
from app.models import Patient
from app.schemas.patient import PatientCreate, PatientIn, PatientUpdate
from app.services.common import apply_updates, paginate
from app.services.hospital_service import get_hospital


async def find_patient(
    db: AsyncSession, hospital_id: uuid.UUID, phone: str, name: str
) -> Patient | None:
    """Look up a patient by identity. `phone` must already be normalized."""
    return await db.scalar(
        select(Patient).where(
            Patient.hospital_id == hospital_id,
            Patient.phone == phone,
            Patient.normalized_name == normalize_name(name),
        )
    )


async def upsert_patient(db: AsyncSession, hospital_id: uuid.UUID, data: PatientIn) -> Patient:
    """Return the patient with this identity, creating it if needed (does not commit).

    Uses INSERT ... ON CONFLICT so two concurrent first bookings for the same new
    patient don't fail on the identity constraint. Optional details provided now
    fill in or update the stored ones; missing ones keep their stored value.
    """
    values = insert(Patient).values(
        hospital_id=hospital_id,
        name=data.name,
        normalized_name=normalize_name(data.name),
        phone=data.phone,
        age=data.age,
        gender=data.gender,
        email=data.email,
        address=data.address,
    )
    excluded = values.excluded
    stmt = values.on_conflict_do_update(
        constraint="uq_patient_hospital_id_phone_normalized_name",
        set_={
            "age": func.coalesce(excluded.age, Patient.age),
            "gender": func.coalesce(excluded.gender, Patient.gender),
            "email": func.coalesce(excluded.email, Patient.email),
            "address": func.coalesce(excluded.address, Patient.address),
            "updated_at": func.now(),
        },
    ).returning(Patient)
    patient: Patient = (await db.scalars(stmt, execution_options={"populate_existing": True})).one()
    return patient


# --- staff / dashboard --------------------------------------------------------------


async def get_patient(db: AsyncSession, patient_id: uuid.UUID) -> Patient:
    patient = await db.get(Patient, patient_id)
    if patient is None:
        raise NotFound("Patient not found")
    return patient


async def create_patient(db: AsyncSession, data: PatientCreate) -> Patient:
    await get_hospital(db, data.hospital_id)
    if await find_patient(db, data.hospital_id, data.phone, data.name):
        raise Conflict("A patient with this phone number and name already exists")
    patient = Patient(
        **data.model_dump(exclude={"name"}),
        name=data.name,
        normalized_name=normalize_name(data.name),
    )
    db.add(patient)
    try:
        await db.commit()
    except IntegrityError as exc:  # lost a race with a concurrent create/booking
        await db.rollback()
        raise Conflict("A patient with this phone number and name already exists") from exc
    await db.refresh(patient)
    return patient


async def search_patients(
    db: AsyncSession,
    *,
    hospital_id: uuid.UUID | None = None,
    phone: str | None = None,
    name: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Patient], int]:
    """`phone` must already be normalized; `name` matches by substring."""
    stmt = select(Patient)
    if hospital_id:
        stmt = stmt.where(Patient.hospital_id == hospital_id)
    if phone:
        stmt = stmt.where(Patient.phone == phone)
    if name:
        stmt = stmt.where(Patient.normalized_name.contains(normalize_name(name), autoescape=True))
    return await paginate(db, stmt.order_by(Patient.name), limit, offset)


async def update_patient(db: AsyncSession, patient_id: uuid.UUID, data: PatientUpdate) -> Patient:
    patient = await get_patient(db, patient_id)
    apply_updates(patient, data.model_dump(exclude_unset=True))
    await db.commit()
    await db.refresh(patient)
    return patient
