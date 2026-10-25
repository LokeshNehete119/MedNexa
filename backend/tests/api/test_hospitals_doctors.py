import uuid

from tests.api.helpers import create_doctor, create_hospital
from tests.factories import next_weekday

MONDAY = next_weekday(1).isoformat()


async def test_hospital_crud(client) -> None:
    hospital = await create_hospital(client)
    assert hospital["timezone"] == "Asia/Kolkata"
    assert hospital["languages"] == ["en", "hi"]

    response = await client.patch(
        f"/api/v1/hospitals/{hospital['id']}", json={"general_instructions": "Bring ID"}
    )
    assert response.json()["general_instructions"] == "Bring ID"

    page = (await client.get("/api/v1/hospitals")).json()
    assert page["total"] == 1 and page["items"][0]["id"] == hospital["id"]


async def test_hospital_validation(client) -> None:
    bad_hours = await client.post(
        "/api/v1/hospitals",
        json={**(await create_hospital(client)), "opening_time": "20:00", "closing_time": "08:00"},
    )
    assert bad_hours.status_code == 422
    bad_tz = await client.post(
        "/api/v1/hospitals",
        json={"name": "X", "address": "Y", "phone": "123", "opening_time": "08:00",
              "closing_time": "09:00", "timezone": "Mars/Base"},
    )  # fmt: skip
    assert bad_tz.status_code == 422


async def test_hospital_update_rejects_inverted_hours(client) -> None:
    hospital = await create_hospital(client)
    response = await client.patch(
        f"/api/v1/hospitals/{hospital['id']}", json={"closing_time": "07:00"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_unknown_hospital_is_404_with_error_body(client) -> None:
    response = await client.get(f"/api/v1/hospitals/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Hospital not found"}}


async def test_info_crud_and_soft_delete(client) -> None:
    hospital = await create_hospital(client)
    url = f"/api/v1/hospitals/{hospital['id']}/info"
    created = await client.post(
        url, json={"category": "Parking", "question": "Parking?", "answer": "Basement"}
    )
    assert created.status_code == 201
    info_id = created.json()["id"]

    updated = await client.patch(f"/api/v1/info/{info_id}", json={"answer": "Basement, free"})
    assert updated.json()["answer"] == "Basement, free"

    assert (await client.delete(f"/api/v1/info/{info_id}")).status_code == 204
    assert (await client.get(url)).json()["total"] == 0
    assert (await client.get(url, params={"include_inactive": True})).json()["total"] == 1


async def test_doctor_crud_and_filters(client) -> None:
    hospital = await create_hospital(client)
    doctor = await create_doctor(client, hospital["id"], available_days=[5, 1, 3, 3])
    assert doctor["available_days"] == [1, 3, 5]
    await create_doctor(client, hospital["id"], name="Dr. Skin", speciality="Dermatology",
                        department="Skin")  # fmt: skip

    cardio = await client.get("/api/v1/doctors", params={"speciality": "cardio"})
    assert [d["name"] for d in cardio.json()["items"]] == ["Dr. Sharma"]

    patched = await client.patch(
        f"/api/v1/doctors/{doctor['id']}", json={"slot_duration_minutes": 15}
    )
    assert patched.json()["slot_duration_minutes"] == 15

    detail = await client.get(f"/api/v1/doctors/{doctor['id']}")
    assert detail.json()["upcoming_overrides"] == []

    assert (await client.delete(f"/api/v1/doctors/{doctor['id']}")).status_code == 204
    active = await client.get("/api/v1/doctors", params={"hospital_id": hospital["id"]})
    assert [d["name"] for d in active.json()["items"]] == ["Dr. Skin"]
    everyone = await client.get("/api/v1/doctors", params={"include_inactive": True})
    assert everyone.json()["total"] == 2


async def test_doctor_validation(client) -> None:
    hospital = await create_hospital(client)
    response = await client.post(
        "/api/v1/doctors",
        json={"hospital_id": hospital["id"], "name": "Dr. X", "speciality": "A", "department": "B",
              "max_daily_appointments": 5, "slot_duration_minutes": 15, "available_days": [8],
              "slot_start_time": "09:00", "slot_end_time": "08:00"},
    )  # fmt: skip
    assert response.status_code == 422

    doctor = await create_doctor(client, hospital["id"])
    inverted = await client.patch(
        f"/api/v1/doctors/{doctor['id']}", json={"slot_end_time": "08:00"}
    )
    assert inverted.status_code == 422

    orphan = await client.post("/api/v1/doctors", json={**doctor, "hospital_id": str(uuid.uuid4())})
    assert orphan.status_code == 404


async def test_schedule_override_endpoints(client) -> None:
    hospital = await create_hospital(client)
    doctor = await create_doctor(client, hospital["id"])
    url = f"/api/v1/doctors/{doctor['id']}/schedule"

    leave = await client.put(url, json={"date": MONDAY, "is_available": False,
                                        "override_reason": "Leave"})  # fmt: skip
    assert leave.status_code == 200
    replaced = await client.put(url, json={"date": MONDAY, "start_time": "10:00"})
    assert replaced.json()["is_available"] is True

    listed = await client.get(url, params={"from": MONDAY, "to": MONDAY})
    assert [o["start_time"] for o in listed.json()] == ["10:00:00"]

    no_hours = await client.put(url, json={"date": MONDAY, "start_time": "13:00"})
    assert no_hours.status_code == 422

    assert (await client.delete(f"{url}/{MONDAY}")).status_code == 204
    assert (await client.delete(f"{url}/{MONDAY}")).status_code == 404
