import pytest

from tests.api.helpers import create_doctor, create_hospital


@pytest.mark.parametrize(
    "body", [{"slot_start_time": None}, {"name": None}, {"available_days": None}]
)
async def test_doctor_patch_rejects_null_for_required_fields(client, body) -> None:
    hospital = await create_hospital(client)
    doctor = await create_doctor(client, hospital["id"])
    response = await client.patch(f"/api/v1/doctors/{doctor['id']}", json=body)
    assert response.status_code == 422


async def test_doctor_patch_allows_clearing_optional_fields(client) -> None:
    hospital = await create_hospital(client)
    doctor = await create_doctor(client, hospital["id"], bio="Cardiologist", qualification="MD")
    response = await client.patch(
        f"/api/v1/doctors/{doctor['id']}", json={"bio": None, "qualification": None}
    )
    assert response.status_code == 200
    assert response.json()["bio"] is None and response.json()["qualification"] is None


@pytest.mark.parametrize("body", [{"closing_time": None}, {"timezone": None}, {"is_active": None}])
async def test_hospital_patch_rejects_null_for_required_fields(client, body) -> None:
    hospital = await create_hospital(client)
    response = await client.patch(f"/api/v1/hospitals/{hospital['id']}", json=body)
    assert response.status_code == 422


async def test_hospital_patch_allows_clearing_optional_fields(client) -> None:
    hospital = await create_hospital(client, email="a@b.in", general_instructions="Bring ID")
    response = await client.patch(
        f"/api/v1/hospitals/{hospital['id']}", json={"email": None, "general_instructions": None}
    )
    assert response.status_code == 200
    assert response.json()["email"] is None


async def test_info_patch_rejects_null(client) -> None:
    hospital = await create_hospital(client)
    info = await client.post(
        f"/api/v1/hospitals/{hospital['id']}/info",
        json={"category": "Parking", "question": "Parking?", "answer": "Yes"},
    )
    response = await client.patch(f"/api/v1/info/{info.json()['id']}", json={"answer": None})
    assert response.status_code == 422
