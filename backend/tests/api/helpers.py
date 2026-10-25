from typing import Any

from httpx import AsyncClient

HOSPITAL = {
    "name": "City Hospital",
    "address": "1 MG Road, Jabalpur",
    "phone": "+917612000000",
    "opening_time": "08:00",
    "closing_time": "20:00",
}


async def create_hospital(client: AsyncClient, **kw: Any) -> dict[str, Any]:
    response = await client.post("/api/v1/hospitals", json={**HOSPITAL, **kw})
    assert response.status_code == 201, response.text
    return response.json()


async def create_doctor(client: AsyncClient, hospital_id: str, **kw: Any) -> dict[str, Any]:
    body = {
        "hospital_id": hospital_id,
        "name": "Dr. Sharma",
        "speciality": "Cardiology",
        "department": "Cardiology",
        "max_daily_appointments": 10,
        "slot_duration_minutes": 30,
        "available_days": [1, 2, 3, 4, 5],
        "slot_start_time": "09:00",
        "slot_end_time": "12:00",
        **kw,
    }
    response = await client.post("/api/v1/doctors", json=body)
    assert response.status_code == 201, response.text
    return response.json()
