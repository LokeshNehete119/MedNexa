"""Seed a sample hospital: doctors, schedule overrides, FAQ entries and bookings.

    uv run python -m scripts.seed           # skip if the sample hospital exists
    uv run python -m scripts.seed --reset   # wipe all data first

Everything goes through the service layer, so seeded data obeys the same rules
as real bookings.
"""

import argparse
import asyncio
from datetime import date, time, timedelta

from sqlalchemy import select, text

from app.core.exceptions import DomainError
from app.core.timeutils import hospital_now
from app.database import SessionFactory, engine
from app.models import Base, BookingSource, Hospital
from app.schemas.appointment import BookingRequest
from app.schemas.doctor import DoctorCreate
from app.schemas.hospital import HospitalCreate, HospitalInfoCreate
from app.schemas.patient import PatientIn
from app.schemas.schedule import ScheduleOverrideIn
from app.services import (
    appointment_service,
    doctor_service,
    hospital_service,
    schedule_service,
    slot_service,
)

HOSPITAL_NAME = "MedNexa City Hospital"

DOCTORS = [
    # name, speciality, department, qualification, days, start, end, slot, cap
    ("Dr. Anil Sharma", "Cardiologist", "Cardiology", "MBBS, MD, DM (Cardiology)",
     [1, 2, 3, 4, 5], time(9), time(13), 15, 16),
    ("Dr. Meera Iyer", "Cardiologist", "Cardiology", "MBBS, MD, DNB (Cardiology)",
     [2, 4, 6], time(14), time(18), 20, 12),
    ("Dr. Rajesh Verma", "Orthopedic Surgeon", "Orthopedics", "MBBS, MS (Ortho)",
     [1, 3, 5], time(10), time(14), 20, 12),
    ("Dr. Kavita Singh", "Orthopedic Surgeon", "Orthopedics", "MBBS, DNB (Ortho)",
     [2, 4, 6], time(9), time(12), 15, 10),
    ("Dr. Suresh Patel", "General Physician", "General Medicine", "MBBS, MD (Medicine)",
     [1, 2, 3, 4, 5, 6], time(9), time(13), 10, 24),
    ("Dr. Anjali Gupta", "General Physician", "General Medicine", "MBBS",
     [1, 2, 3, 4, 5], time(16), time(20), 10, 20),
]  # fmt: skip

FAQ = [
    ("Timings", "What are the OPD timings?",
     "OPD runs Monday to Saturday, 9 AM to 8 PM. Emergency is open 24x7."),
    ("Location", "Where is the hospital located?",
     "12 Civil Lines, near Gol Bazaar, Jabalpur, Madhya Pradesh 482001."),
    ("Parking", "Is parking available?",
     "Free parking for cars and two-wheelers is available in the basement."),
    ("Emergency", "Is there an emergency department?",
     "Yes, the emergency department and ambulance service (call 108) are available 24x7."),
    ("Pharmacy", "Is there a pharmacy in the hospital?",
     "The in-house pharmacy on the ground floor is open 24 hours."),
    ("Insurance", "Which insurance and payment options are accepted?",
     "Cashless treatment is available with major insurers and Ayushman Bharat. "
     "Cash, cards and UPI are accepted."),
    ("Departments", "Which departments are available?",
     "Cardiology, Orthopedics and General Medicine, plus radiology and pathology labs."),
    ("Reports", "How do I collect lab reports?",
     "Lab reports are ready within 24 hours and can be collected at the pathology "
     "counter or received on WhatsApp."),
]  # fmt: skip

PATIENTS = [
    ("Rahul Kumar", "+919876543210", 34, "MALE"),
    ("Sita Kumar", "+919876543210", 31, "FEMALE"),  # same phone, different patient
    ("Priya Sharma", "+919812345678", 27, "FEMALE"),
    ("Mohan Lal", "+919900112233", 62, "MALE"),
]


def next_working_day(after: date, days: list[int]) -> date:
    d = after + timedelta(days=1)
    while d.isoweekday() not in days:
        d += timedelta(days=1)
    return d


async def reset() -> None:
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


async def seed() -> None:
    async with SessionFactory() as db:
        if await db.scalar(select(Hospital).where(Hospital.name == HOSPITAL_NAME)):
            print(f"'{HOSPITAL_NAME}' already exists; use --reset to recreate it.")
            return

        hospital = await hospital_service.create_hospital(
            db,
            HospitalCreate(
                name=HOSPITAL_NAME,
                address="12 Civil Lines, Jabalpur, Madhya Pradesh 482001",
                phone="+917612400000",
                email="reception@mednexa.example",
                opening_time=time(9),
                closing_time=time(20),
                general_instructions="Patients should arrive 15 minutes before their slot.",
            ),
        )
        for category, question, answer in FAQ:
            await hospital_service.create_info(
                db,
                hospital.id,
                HospitalInfoCreate(category=category, question=question, answer=answer),
            )

        doctors = []
        for name, spec, dept, qual, days, start, end, slot, cap in DOCTORS:
            doctors.append(
                await doctor_service.create_doctor(
                    db,
                    DoctorCreate(
                        hospital_id=hospital.id,
                        name=name,
                        speciality=spec,
                        department=dept,
                        qualification=qual,
                        available_days=days,
                        slot_start_time=start,
                        slot_end_time=end,
                        slot_duration_minutes=slot,
                        max_daily_appointments=cap,
                    ),
                )
            )

        today = hospital_now(hospital.timezone).date()
        sharma, iyer, verma, *_ = doctors
        leave_day = next_working_day(today + timedelta(days=7), sharma.available_days)
        await schedule_service.upsert_override(
            db,
            sharma.id,
            ScheduleOverrideIn(date=leave_day, is_available=False, override_reason="Conference"),
        )
        short_day = next_working_day(today + timedelta(days=7), verma.available_days)
        await schedule_service.upsert_override(
            db,
            verma.id,
            ScheduleOverrideIn(date=short_day, end_time=time(12), override_reason="Surgery at 12"),
        )

        bookings = [
            (PATIENTS[0], sharma, 0),
            (PATIENTS[1], sharma, 1),
            (PATIENTS[2], iyer, 0),
            (PATIENTS[3], verma, 0),
        ]
        booked = 0
        for (name, phone, age, gender), doctor, slot_index in bookings:
            on = next_working_day(today, doctor.available_days)
            slots = await slot_service.get_available_slots(db, doctor.id, on)
            try:
                await appointment_service.book_appointment(
                    db,
                    BookingRequest(
                        patient=PatientIn(name=name, phone=phone, age=age, gender=gender),
                        doctor_id=doctor.id,
                        appointment_date=on,
                        appointment_time=slots[slot_index].start,
                        booking_source=BookingSource.DASHBOARD,
                    ),
                )
                booked += 1
            except (DomainError, IndexError) as exc:
                print(f"Skipped a sample booking for {name}: {exc}")

        print(
            f"Seeded '{HOSPITAL_NAME}' ({hospital.id}): {len(doctors)} doctors, "
            f"{len(FAQ)} FAQ entries, 2 schedule overrides, {booked} appointments."
        )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reset", action="store_true", help="delete all data first")
    args = parser.parse_args()
    if args.reset:
        await reset()
    await seed()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
