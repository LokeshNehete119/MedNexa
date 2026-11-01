# MedNexa Voice & Telephony Setup & Run Guide

This document explains how to start, configure, and test MedNexa voice calls.

---

## 🛠️ Summary of Fixes Applied to the Codebase

Before running, note that the following bugs were identified and fixed:

1. **Structured Logging Crash** (`telephony/telephony/logging_setup.py` & `main.py`):
   - Fixed `AttributeError: 'PrintLogger' object has no attribute 'name'` by configuring structlog to use `stdlib.LoggerFactory()` and calling `configure_logging()` at module import time.
2. **Silero VAD Interactive Prompt Crash** (`telephony/telephony/vad.py`):
   - Added `trust_repo=True` to `torch.hub.load(...)` so it does not fail with `EOFError` when running non-interactively in Docker.
3. **Web Phone Interface** (`telephony/telephony/main.py`):
   - Added a built-in mobile/browser phone simulator at `GET /call` that connects directly via WebSocket for instant testing without telecom OTP or ISD costs.

---

## 🚀 Step 1: Starting the Services

To start all services in Docker (Database, API, Telephony, Dashboard, Ollama):

```bash
cd /home/parth/Cloned_repos/MedNexa
docker compose up -d
```

### Check service health:
```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

Expected running containers:
- `mednexa-api` (Port `8000`) - Backend REST API
- `mednexa-dashboard` (Port `3001`) - Staff Dashboard
- `mednexa-telephony` (Port `8001`) - Voice pipeline (VAD + Whisper STT + TTS)
- `mednexa-db` (Port `5434`) - PostgreSQL
- `mednexa-ollama` (Port `11434`) - Local LLM Server

---

## 🧠 Step 2: Configure the AI Brain (LLM)

When a caller speaks, the agent needs an LLM to generate responses. You have two options:

### Option A: Groq Cloud API (Recommended for Voice - Near Instant)
Groq gives ~200ms response latency, which makes phone conversations feel natural.

1. Get a free API key at [console.groq.com/keys](https://console.groq.com/keys).
2. Open `.env` and set:
   ```dotenv
   MEDNEXA_AGENT_LLM_MODE=cloud
   MEDNEXA_AGENT_CLOUD_PROVIDER=groq
   MEDNEXA_AGENT_GROQ_API_KEY=gsk_your_key_here
   ```
3. Restart telephony:
   ```bash
   docker compose up -d telephony
   ```

### Option B: Local Ollama (100% Offline)
If you prefer running completely locally:

1. Pull the model into the running Ollama container:
   ```bash
   docker exec -d mednexa-ollama ollama pull llama3.1:8b
   ```
2. Monitor download progress:
   ```bash
   docker logs -f mednexa-ollama
   ```
3. Once completed, calls will use your local CPU/GPU for responses.

---

## 📞 Step 3: Testing Calls

### Method 1: Web Phone from your Mobile (Easiest & Free)
This works anywhere without Twilio phone verification or international charges.

1. **Start ngrok** to expose the telephony service (port 8001):
   ```bash
   ngrok http 8001
   ```
2. Copy the HTTPS URL provided by ngrok (e.g. `https://your-domain.ngrok-free.dev`).
3. Open this link on your **Mobile Phone's browser**:
   ```
   https://your-domain.ngrok-free.dev/call
   ```
4. Tap the **green phone button 📞**, allow microphone access, and speak directly into your phone!

---

### Method 2: Real Phone Call via Twilio (Cellular Dial)
If you want to dial from your phone's cellular network:

1. **Verify your personal phone number on Twilio**:
   - Go to [Twilio Console → Verified Caller IDs](https://console.twilio.com/us1/develop/phone-numbers/manage/verified).
   - Click **Add Caller ID**, enter your Indian mobile number (+91...).
   - **Important**: Choose **"Call me"** (Phone call verification) rather than SMS, as international SMS is filtered in India.
2. **Update your `.env`**:
   ```dotenv
   MEDNEXA_TEL_TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxx
   MEDNEXA_TEL_TWILIO_AUTH_TOKEN=your_token
   MEDNEXA_TEL_TWILIO_PHONE_NUMBER=+17372508034
   MEDNEXA_TEL_PUBLIC_URL=https://your-domain.ngrok-free.dev
   ```
3. **Configure Twilio Webhook**:
   - Go to [Twilio Console → Active Phone Numbers](https://console.twilio.com/us1/develop/phone-numbers/manage/incoming).
   - Click your phone number.
   - Under **Voice Configuration**, set **A CALL COMES IN** to:
     - Webhook: `https://your-domain.ngrok-free.dev/twilio/voice`
     - Method: `HTTP POST`
   - Click **Save**.
4. Restart telephony:
   ```bash
   docker compose up -d telephony
   ```
5. Dial `+1 737 250 8034` from your verified phone.

---

## 🛑 Step 4: Stopping Services

To stop and shut down all containers at any time:

```bash
docker compose down
```

---

## 📊 Useful URLs & Credentials

| Service | URL | Notes / Credentials |
|---|---|---|
| **Staff Dashboard** | `http://localhost:3001` | User: `admin@mednexa.com`<br>Pass: `12345678` |
| **API Swagger Docs** | `http://localhost:8000/docs` | Interactive REST API |
| **Telephony Health** | `http://localhost:8001/health` | Check telephony pipeline status |
| **Web Phone Interface** | `http://localhost:8001/call` | Or via your ngrok HTTPS URL |

