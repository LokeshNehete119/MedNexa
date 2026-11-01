# MedNexa API – Quick Call Reference

> [!IMPORTANT]
> **Base URL:** `http://localhost:8000` (bound only to `127.0.0.1`)
> **Dashboard:** `http://localhost:3001`
> **Interactive Docs (Swagger):** `http://localhost:8000/docs`
> **ReDoc:** `http://localhost:8000/redoc`

---

## 🟢 Live Container Status

| Container | Port | Status |
|---|---|---|
| `mednexa-api` | `127.0.0.1:8000` | ✅ Healthy |
| `mednexa-dashboard` | `0.0.0.0:3001` | ✅ Healthy |
| `mednexa-db` | `127.0.0.1:5434` | ✅ Healthy |
| `mednexa-ollama` | `11434` (internal) | ✅ Up |
| `mednexa-telephony` | — | ⚠️ Restarting (needs `MEDNEXA_TEL_HOSPITAL_ID`) |

---

## Step 1 — Get a Token (Login)

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@mednexa.com","password":"12345678"}'
```

**Response gives you** `access_token`. Export it for all subsequent calls:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@mednexa.com","password":"12345678"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo $TOKEN
```

> [!NOTE]
> Token is valid for **2 hours** (`expires_in: 7200`). Re-run the login command to refresh it.

---

## Step 2 — Health Check (No Auth)

```bash
curl http://localhost:8000/api/v1/health
# → {"status":"ok","database":"ok"}
```

---

## 🏥 Hospitals

**Seeded hospital ID:** `0a342a10-86e6-4a66-ab77-4e16ec039d35`

```bash
# List hospitals
curl http://localhost:8000/api/v1/hospitals \
  -H "Authorization: Bearer $TOKEN"

# Get one hospital
curl http://localhost:8000/api/v1/hospitals/0a342a10-86e6-4a66-ab77-4e16ec039d35 \
  -H "Authorization: Bearer $TOKEN"

# Create a hospital
curl -X POST http://localhost:8000/api/v1/hospitals \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Hospital",
    "address": "123 Main St",
    "phone": "+911234567890",
    "email": "test@hospital.com",
    "opening_time": "09:00",
    "closing_time": "18:00",
    "timezone": "Asia/Kolkata",
    "languages": ["en"]
  }'
```

---

## 👨‍⚕️ Doctors

**Seeded doctors:**

| Name | Speciality | ID |
|---|---|---|
| Dr. Anil Sharma | Cardiologist | `73e32ed2-8a40-47a5-966b-9cbb833d168f` |
| Dr. Anjali Gupta | General Physician | `cfb53fb5-ba24-4711-b892-3d66e7b91ab7` |
| Dr. Kavita Singh | Orthopedic Surgeon | `61b5692c-9f25-4fd4-a2cf-dcd815e2f705` |
| Dr. Meera Iyer | Cardiologist | `f50eaa76-04e6-4c09-83b7-f871d3ee7856` |
| Dr. Rajesh Verma | Orthopedic Surgeon | `9bf743ab-f4cc-45b4-b07a-a4ae79782bd1` |
| Dr. Suresh Patel | General Physician | `35a2b7a7-e772-4207-963a-d026047daad2` |

```bash
# List all doctors
curl http://localhost:8000/api/v1/doctors \
  -H "Authorization: Bearer $TOKEN"

# Get a doctor's available slots (replace DATE with e.g. 2026-11-03)
curl "http://localhost:8000/api/v1/doctors/73e32ed2-8a40-47a5-966b-9cbb833d168f/slots?date=2026-11-03" \
  -H "Authorization: Bearer $TOKEN"

# Next available slot across all doctors
curl "http://localhost:8000/api/v1/slots/next-available?hospital_id=0a342a10-86e6-4a66-ab77-4e16ec039d35" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 🧑 Patients

```bash
# List patients
curl http://localhost:8000/api/v1/patients \
  -H "Authorization: Bearer $TOKEN"

# Create a patient
curl -X POST http://localhost:8000/api/v1/patients \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Rahul Sharma",
    "phone": "+919876543210",
    "date_of_birth": "1990-05-15",
    "gender": "male"
  }'
```

---

## 📅 Appointments

```bash
# List all appointments
curl http://localhost:8000/api/v1/appointments \
  -H "Authorization: Bearer $TOKEN"

# Book an appointment (replace patient_id, doctor_id, slot_time)
curl -X POST http://localhost:8000/api/v1/appointments \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "patient_id": "<patient_id>",
    "doctor_id": "73e32ed2-8a40-47a5-966b-9cbb833d168f",
    "hospital_id": "0a342a10-86e6-4a66-ab77-4e16ec039d35",
    "slot_time": "2026-11-03T09:00:00"
  }'

# Cancel
curl -X POST http://localhost:8000/api/v1/appointments/<appt_id>/cancel \
  -H "Authorization: Bearer $TOKEN"

# Reschedule
curl -X POST http://localhost:8000/api/v1/appointments/<appt_id>/reschedule \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"slot_time": "2026-11-04T09:00:00"}'
```

---

## 📞 Calls (Telephony / AI Agent)

```bash
# Start a new call session (uses SERVICE API KEY, not JWT)
curl -X POST http://localhost:8000/api/v1/calls \
  -H "X-Api-Key: 11f8e516c8cdc69256611282e779b100bf1c7f5d183dd58b358fef11fd858b36" \
  -H "Content-Type: application/json" \
  -d '{
    "hospital_id": "0a342a10-86e6-4a66-ab77-4e16ec039d35",
    "caller_phone": "+919876543210"
  }'

# List all call logs (JWT)
curl http://localhost:8000/api/v1/calls \
  -H "Authorization: Bearer $TOKEN"
```

> [!NOTE]
> The `telephony` container is **restarting** because `MEDNEXA_TEL_HOSPITAL_ID` is empty in `.env`.
> Set it to `0a342a10-86e6-4a66-ab77-4e16ec039d35` and run `docker compose up -d telephony` to fix it.

---

## 🔑 Credentials Summary

| What | Value |
|---|---|
| Admin email | `admin@mednexa.com` |
| Admin password | `12345678` |
| Service API Key | `11f8e516c8cdc69256611282e779b100bf1c7f5d183dd58b358fef11fd858b36` |
| Hospital ID | `0a342a10-86e6-4a66-ab77-4e16ec039d35` |

