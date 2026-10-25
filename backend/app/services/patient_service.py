import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.normalize import normalize_name
from app.models import Patient
from app.schemas.patient import PatientIn


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
