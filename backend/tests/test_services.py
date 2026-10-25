"""Service-level tests for the agent lookups and admin helpers not covered elsewhere."""

import asyncio
from datetime import time, timedelta

import pytest

from app.core.exceptions import Conflict, DomainValidationError, NotFound
from app.models import CallOutcome, CallRole, Doctor
from app.schemas.call import CallLogCreate, CallSessionCreate, CallSessionEnd
from app.schemas.hospital import HospitalInfoCreate
from app.schemas.patient import PatientCreate
from app.schemas.schedule import ScheduleOverrideIn
from app.services import (
    call_service,
    contracts,
    hospital_service,
    patient_service,
    schedule_service,
)
from tests.factories import make_doctor, make_hospital, next_weekday

MONDAY = next_weekday(1)


async def test_hospital_info_ranks_by_keyword_overlap(db) -> None:
    hospital = await make_hospital(db)
    for category, question, answer in [
        ("Parking", "Is there parking?", "Free parking in basement for cars and bikes."),
        ("Timings", "What are OPD timings?", "OPD runs 9am to 5pm, Monday to Saturday."),
        ("Pharmacy", "Is the pharmacy open at night?", "The pharmacy is open 24 hours."),
    ]:
        await hospital_service.create_info(
            db, hospital.id, HospitalInfoCreate(category=category, question=question, answer=answer)
        )

    results = await contracts.get_hospital_info(db, hospital.id, "Where can I park my car?")
    assert results[0].category == "Parking"
    assert await contracts.get_hospital_info(db, hospital.id, "helicopter landing") == []
    assert len(await contracts.get_hospital_info(db, hospital.id, "what is the")) == 3


async def test_deactivated_info_is_hidden_from_agent(db) -> None:
    hospital = await make_hospital(db)
    info = await hospital_service.create_info(
        db, hospital.id, HospitalInfoCreate(category="Parking", question="Parking?", answer="Yes")
    )
    await hospital_service.deactivate_info(db, info.id)
    assert await contracts.get_hospital_info(db, hospital.id, "parking") == []


async def test_list_doctors_filters_and_hides_inactive(db) -> None:
    hospital = await make_hospital(db)
    await make_doctor(db, hospital, name="Dr. Heart")
    await make_doctor(db, hospital, name="Dr. Skin", speciality="Dermatology", department="Skin")
    await make_doctor(db, hospital, name="Dr. Gone", is_active=False)

    names = [d.name for d in await contracts.list_doctors(db, hospital.id, speciality="cardio")]
    assert names == ["Dr. Heart"]
    assert len(await contracts.list_doctors(db, hospital.id)) == 2


async def test_get_doctor_includes_upcoming_overrides(db) -> None:
    hospital = await make_hospital(db)
    doctor = await make_doctor(db, hospital)
    await schedule_service.upsert_override(
        db, doctor.id, ScheduleOverrideIn(date=MONDAY, is_available=False, override_reason="Leave")
    )
    detail = await contracts.get_doctor(db, doctor.id)
    assert [o.override_reason for o in detail.upcoming_overrides] == ["Leave"]


async def test_override_upsert_replaces_and_validates(db) -> None:
    hospital = await make_hospital(db)
    doctor = await make_doctor(db, hospital)  # template 09:00-12:00
    await schedule_service.upsert_override(
        db, doctor.id, ScheduleOverrideIn(date=MONDAY, is_available=False)
    )
    updated = await schedule_service.upsert_override(
        db, doctor.id, ScheduleOverrideIn(date=MONDAY, start_time=time(10))
    )
    assert updated.is_available and updated.start_time == time(10)
    assert len(await schedule_service.list_overrides(db, doctor.id, None, None)) == 1

    with pytest.raises(DomainValidationError):  # start after template end: no working time
        await schedule_service.upsert_override(
            db, doctor.id, ScheduleOverrideIn(date=MONDAY, start_time=time(13))
        )

    await schedule_service.delete_override(db, doctor.id, MONDAY)
    with pytest.raises(NotFound):
        await schedule_service.delete_override(db, doctor.id, MONDAY)


async def test_create_patient_rejects_duplicate_identity(db) -> None:
    hospital = await make_hospital(db)
    data = PatientCreate(hospital_id=hospital.id, name="Rahul Kumar", phone="9876543210")
    await patient_service.create_patient(db, data)
    with pytest.raises(Conflict):
        await patient_service.create_patient(
            db, PatientCreate(hospital_id=hospital.id, name="RAHUL kumar", phone="+919876543210")
        )


async def test_call_lifecycle(db) -> None:
    hospital = await make_hospital(db)
    session = await call_service.start_call(
        db, CallSessionCreate(hospital_id=hospital.id, caller_phone="98765 43210")
    )
    assert session.caller_phone == "+919876543210"

    for role in (CallRole.ASSISTANT, CallRole.USER, CallRole.TOOL):
        await call_service.append_log(db, session.id, CallLogCreate(role=role, content="..."))
    await call_service.end_call(
        db, session.id, CallSessionEnd(call_outcome=CallOutcome.INFO_PROVIDED, summary="Asked OPD")
    )

    detail = await call_service.get_call(db, session.id)
    assert detail.total_turns == 2  # tool entries don't count as turns
    assert [log.role for log in detail.logs] == [CallRole.ASSISTANT, CallRole.USER, CallRole.TOOL]
    assert detail.call_end is not None
    assert detail.call_end - detail.call_start < timedelta(minutes=1)

    call_id = session.id  # a rejected write rolls back and expires loaded objects
    with pytest.raises(DomainValidationError):
        await call_service.append_log(db, call_id, CallLogCreate(role=CallRole.USER, content="x"))
    with pytest.raises(DomainValidationError):
        await call_service.end_call(db, call_id, CallSessionEnd(call_outcome=CallOutcome.OTHER))


async def test_doctor_search_treats_wildcards_literally(db) -> None:
    hospital = await make_hospital(db)
    await make_doctor(db, hospital, name="Dr. Heart")
    await make_doctor(db, hospital, name="Dr. Skin", speciality="Dermatology", department="Skin")

    for pattern in ("%", "_", "Cardi_logy"):
        assert await contracts.list_doctors(db, hospital.id, speciality=pattern) == []
    # A blank filter means "no filter" when listing.
    assert len(await contracts.list_doctors(db, hospital.id, speciality="   ")) == 2


async def test_next_available_rejects_blank_and_wildcard_speciality(db) -> None:
    hospital = await make_hospital(db)
    await make_doctor(db, hospital)
    for speciality in ("   ", "%", "_"):
        assert await contracts.find_next_available(db, hospital.id, speciality) == []


async def test_list_doctors_is_not_capped(db) -> None:
    hospital = await make_hospital(db)
    db.add_all(
        Doctor(
            hospital_id=hospital.id, name=f"Dr. {i:03d}", speciality="General", department="OPD",
            max_daily_appointments=10, slot_duration_minutes=15, available_days=[1],
            slot_start_time=time(9), slot_end_time=time(10),
        )
        for i in range(205)
    )  # fmt: skip
    await db.commit()
    assert len(await contracts.list_doctors(db, hospital.id)) == 205


async def test_concurrent_logs_and_end_never_leave_logs_on_ended_call(db, session_factory) -> None:
    hospital = await make_hospital(db)
    call = await call_service.start_call(
        db, CallSessionCreate(hospital_id=hospital.id, caller_phone="9876543210")
    )

    async def append(i: int):
        async with session_factory() as s:
            try:
                return await call_service.append_log(
                    s, call.id, CallLogCreate(role=CallRole.USER, content=str(i))
                )
            except DomainValidationError as exc:
                return exc

    async def end():
        async with session_factory() as s:
            return await call_service.end_call(
                s, call.id, CallSessionEnd(call_outcome=CallOutcome.OTHER)
            )

    results = await asyncio.gather(
        *(append(i) for i in range(10)), end(), *(append(i) for i in range(10, 20))
    )
    accepted = [r for r in results[:10] + results[11:] if not isinstance(r, Exception)]

    async with session_factory() as fresh:
        detail = await call_service.get_call(fresh, call.id)
    assert detail.total_turns == len(detail.logs) == len(accepted)
    # Every accepted log committed before the call ended (row lock serialises them).
    assert all(log.timestamp <= detail.call_end for log in detail.logs)


async def test_override_upsert_bumps_updated_at(db) -> None:
    hospital = await make_hospital(db)
    doctor = await make_doctor(db, hospital)
    first = await schedule_service.upsert_override(
        db, doctor.id, ScheduleOverrideIn(date=MONDAY, is_available=False)
    )
    created_at, first_updated = first.created_at, first.updated_at
    second = await schedule_service.upsert_override(
        db, doctor.id, ScheduleOverrideIn(date=MONDAY, start_time=time(10))
    )
    assert second.created_at == created_at
    assert second.updated_at > first_updated
