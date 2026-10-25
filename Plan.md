# MedNexa — Agentic AI Hospital Receptionist

## Implementation Plan (5-Part Division)

---

## 0. Executive Summary

**MedNexa** is a voice-enabled, agentic AI receptionist that answers hospital phone calls, provides hospital/doctor information, and books or cancels patient appointments — all autonomously. Hospitals manage their data (doctors, schedules, general info) through a web admin dashboard, and the AI agent reads this data in real time to give accurate answers.

### Core Capabilities

| Capability | Details |
|---|---|
| **Voice Calls** | Picks up incoming calls via SIP/VoIP, converses naturally |
| **Bilingual** | Fluent English and Hindi (auto-detect + switch mid-call) |
| **Appointment Booking** | Collects patient info, checks slot availability, books with conflict detection |
| **Appointment Cancellation** | Verifies caller identity, cancels confirmed bookings |
| **Status Inquiry** | Tells callers their own appointment status (after identity verification) |
| **Hospital Info** | Answers questions about address, OPD timings, departments, parking, etc. |
| **Multi-booking** | Same phone → different patients → parallel bookings allowed; same patient → different time-slots only |
| **Human Handoff** | Escalates to human staff when confidence is low (Phase 2) |

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    HOSPITAL LOCAL SERVER                     │
│                                                             │
│  ┌──────────┐   ┌──────────────┐   ┌───────────────────┐   │
│  │ Telephony│──▶│ AI Agent Core│──▶│  Database (SQLite/ │   │
│  │ Gateway  │◀──│ (LLM + Tools)│◀──│  PostgreSQL)       │   │
│  │ (SIP/    │   └──────┬───────┘   └───────────────────┘   │
│  │  WebRTC) │          │                    ▲               │
│  └──────────┘   ┌──────▼───────┐            │               │
│                 │  STT Engine  │   ┌────────┴────────┐      │
│                 │  (Whisper)   │   │  Admin Dashboard │      │
│                 └──────────────┘   │  (Next.js / Web) │      │
│                 ┌──────────────┐   └─────────────────┘      │
│                 │  TTS Engine  │                             │
│                 │ (Piper/Edge) │                             │
│                 └──────────────┘                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 1. Technology Stack

| Layer | Primary Choice | Fallback / Cloud Option | Rationale |
|---|---|---|---|
| **Language** | Python 3.11+ | — | Rich AI/ML ecosystem, async support |
| **Web Framework** | FastAPI | — | Async, OpenAPI docs, WebSocket support |
| **Database** | SQLite (dev) → PostgreSQL (prod) | — | Zero-config start, easy migration |
| **ORM** | SQLAlchemy 2.0 + Alembic | — | Async support, migration management |
| **LLM (Local)** | Ollama + `llama3.1:8b` or `mistral-nemo:12b` | Groq API (free tier) / OpenAI | Runs on local GPU; fallback if too slow or hallucinating |
| **LLM Framework** | LangGraph (tool-calling agent) | LangChain fallback | Stateful, graph-based agent with tool use |
| **STT** | Faster-Whisper (local, CTranslate2) | Deepgram API / Google STT | Real-time, runs on CPU/GPU, Hindi+English |
| **TTS** | Piper TTS (local, ONNX) | Edge-TTS (free, Microsoft) / ElevenLabs | Fast, low-latency, Hindi+English voices |
| **Telephony** | Asterisk PBX + ARI | Twilio (cloud) | Local SIP trunk; Twilio for quick prototype |
| **Admin Dashboard** | Next.js 14 (App Router) | — | React-based, SSR, API routes |
| **Task Queue** | Celery + Redis | — | Background jobs (reminders, cleanup) |
| **Caching** | Redis | — | Session state, rate limiting |
| **Containerization** | Docker + Docker Compose | — | Reproducible local deployment |

### Local Model Strategy

```
┌─────────────────────────────────────────────────────────┐
│                    MODEL SELECTION LOGIC                  │
│                                                          │
│  1. Try LOCAL model first (Ollama)                        │
│     ├─ Response time < 3s? ──▶ USE LOCAL                 │
│     └─ Response time > 3s OR hallucination detected?     │
│           └─▶ Fallback to CLOUD API (Groq / OpenAI)     │
│                                                          │
│  2. Config flag: FORCE_LOCAL=true / FORCE_CLOUD=true     │
│  3. Per-task routing:                                    │
│     ├─ Simple slot queries ──▶ LOCAL (fast enough)       │
│     ├─ Complex conversations ──▶ LOCAL or CLOUD          │
│     └─ Hindi conversations ──▶ CLOUD (better quality)   │
└─────────────────────────────────────────────────────────┘
```

**LLM Abstraction Layer**: We build a `ModelRouter` class that:
- Wraps both local (Ollama) and cloud (Groq/OpenAI) providers behind a unified interface
- Measures latency per call and logs it
- Has a circuit-breaker: if local fails 3x in a row, auto-switch to cloud for N minutes
- Configurable via `config.yaml` — hospital admin can choose preferred mode

---

## 2. Database Schema Design

### How the AI Handles the Database

> [!IMPORTANT]
> The AI agent does **NOT** write raw SQL. Instead, it calls **Python tool functions** that are registered with the LangGraph agent. Each tool function encapsulates a specific DB operation with validation, conflict checks, and transaction safety.

```
AI Agent (LLM)
    │
    ├── calls tool: "check_available_slots(doctor_id, date)"
    │       └── Python function → SQLAlchemy query → returns JSON
    │
    ├── calls tool: "book_appointment(patient_name, phone, doctor_id, slot_time)"
    │       └── Python function → validates → INSERT with row-lock → returns confirmation
    │
    ├── calls tool: "cancel_appointment(appointment_id, phone)"
    │       └── Python function → verifies ownership → UPDATE status → returns result
    │
    └── calls tool: "get_hospital_info(query_type)"
            └── Python function → SELECT from hospital_info → returns text
```

### Entity-Relationship Diagram

```mermaid
erDiagram
    HOSPITAL ||--o{ DOCTOR : employs
    HOSPITAL ||--o{ HOSPITAL_INFO : has
    DOCTOR ||--o{ SCHEDULE : has
    DOCTOR ||--o{ APPOINTMENT : receives
    PATIENT ||--o{ APPOINTMENT : books
    APPOINTMENT ||--o{ CALL_LOG : discussed_in
    CALL_SESSION ||--o{ CALL_LOG : contains

    HOSPITAL {
        uuid id PK
        string name
        string address
        string phone
        string email
        time opening_time
        time closing_time
        string[] languages
        text general_instructions
        boolean is_active
        timestamp created_at
        timestamp updated_at
    }

    HOSPITAL_INFO {
        uuid id PK
        uuid hospital_id FK
        string category
        string question
        text answer
        boolean is_active
        timestamp updated_at
    }

    DOCTOR {
        uuid id PK
        uuid hospital_id FK
        string name
        string speciality
        string qualification
        string department
        int max_daily_appointments
        int slot_duration_minutes
        string[] available_days
        time slot_start_time
        time slot_end_time
        boolean is_active
        text bio
        timestamp created_at
        timestamp updated_at
    }

    SCHEDULE {
        uuid id PK
        uuid doctor_id FK
        date date
        time start_time
        time end_time
        boolean is_available
        string override_reason
        timestamp created_at
    }

    PATIENT {
        uuid id PK
        string name
        string phone
        int age
        string gender
        string email
        text address
        timestamp created_at
        timestamp updated_at
    }

    APPOINTMENT {
        uuid id PK
        uuid patient_id FK
        uuid doctor_id FK
        uuid hospital_id FK
        date appointment_date
        time appointment_time
        int slot_duration_minutes
        string status
        string booking_source
        text notes
        string token_number
        timestamp created_at
        timestamp updated_at
        timestamp cancelled_at
        string cancellation_reason
    }

    CALL_SESSION {
        uuid id PK
        uuid hospital_id FK
        string caller_phone
        timestamp call_start
        timestamp call_end
        string language_detected
        string call_outcome
        text summary
        boolean escalated_to_human
        int total_turns
    }

    CALL_LOG {
        uuid id PK
        uuid session_id FK
        uuid appointment_id FK
        string role
        text content
        string tool_called
        text tool_result
        timestamp timestamp
    }
```

### Key Constraints & Business Rules

| Rule | Implementation |
|---|---|
| Same phone, different patient names → allowed parallel bookings | `UNIQUE(patient_id, doctor_id, appointment_date, appointment_time)` — not on phone alone |
| Same patient, same doctor, same time → blocked | Composite unique constraint + app-level check in booking tool |
| Same patient, different doctor, same time → allowed | No constraint across doctors for same patient |
| Same patient, same doctor, different time → allowed | Unique constraint permits this |
| Slot capacity | `COUNT(appointments) < doctor.max_daily_appointments` checked before INSERT |
| Caller verification | Phone number match required to view/cancel; optionally OTP via SMS |
| Appointment status enum | `BOOKED`, `CANCELLED`, `COMPLETED`, `NO_SHOW`, `RESCHEDULED` |

---

## 3. AI Agent Architecture (LangGraph)

### Agent State Machine

```mermaid
stateDiagram-v2
    [*] --> Greeting
    Greeting --> LanguageDetection: caller speaks
    LanguageDetection --> IntentClassification: language identified
    IntentClassification --> HospitalInfoFlow: intent = info_query
    IntentClassification --> BookingFlow: intent = book_appointment
    IntentClassification --> CancellationFlow: intent = cancel_appointment
    IntentClassification --> StatusFlow: intent = check_status
    IntentClassification --> HumanHandoff: intent = unclear / complex

    HospitalInfoFlow --> AnswerQuery: fetch from DB
    AnswerQuery --> AskIfAnythingElse
    
    BookingFlow --> CollectPatientInfo: ask name, age, gender
    CollectPatientInfo --> CollectDoctorPreference: ask speciality or doctor name
    CollectDoctorPreference --> CheckAvailability: query slots
    CheckAvailability --> OfferSlots: slots available
    CheckAvailability --> SuggestAlternatives: no slots
    OfferSlots --> ConfirmBooking: patient confirms
    ConfirmBooking --> BookingSuccess: DB updated
    SuggestAlternatives --> CollectDoctorPreference: try different doctor/date
    
    CancellationFlow --> VerifyIdentity: ask phone + name
    VerifyIdentity --> ShowAppointments: verified
    ShowAppointments --> ConfirmCancel: patient picks one
    ConfirmCancel --> CancelSuccess: DB updated
    
    StatusFlow --> VerifyIdentity
    VerifyIdentity --> ShowStatus: verified
    
    AskIfAnythingElse --> IntentClassification: new intent
    AskIfAnythingElse --> Goodbye: nothing else
    BookingSuccess --> AskIfAnythingElse
    CancelSuccess --> AskIfAnythingElse
    ShowStatus --> AskIfAnythingElse
    Goodbye --> [*]
```

### Tool Functions (AI's DB Interface)

```python
# These are the tools the LLM agent can invoke via LangGraph tool-calling

@tool
def get_hospital_info(query: str) -> str:
    """Search hospital general information (address, timings, departments, parking, etc.)"""

@tool
def list_doctors(speciality: Optional[str] = None, department: Optional[str] = None) -> list[dict]:
    """List available doctors, optionally filtered by speciality or department."""

@tool
def get_doctor_details(doctor_id: str) -> dict:
    """Get full details of a specific doctor including schedule."""

@tool
def check_available_slots(doctor_id: str, date: str) -> list[dict]:
    """Check available appointment slots for a doctor on a given date."""

@tool
def find_next_available(speciality: str, preferred_date: Optional[str] = None) -> list[dict]:
    """Find next available slots across all doctors of a given speciality."""

@tool
def book_appointment(
    patient_name: str, 
    patient_phone: str, 
    patient_age: int,
    patient_gender: str,
    doctor_id: str, 
    appointment_date: str, 
    appointment_time: str,
    notes: Optional[str] = None
) -> dict:
    """Book an appointment. Returns confirmation with token number or error."""

@tool
def cancel_appointment(appointment_id: str, caller_phone: str) -> dict:
    """Cancel an appointment after verifying caller owns it via phone match."""

@tool
def get_patient_appointments(phone: str, patient_name: str) -> list[dict]:
    """Get appointments for a verified patient (phone + name must match)."""

@tool
def get_current_datetime() -> str:
    """Get the current date, time, and day of week."""
```

### System Prompt Structure

```
You are MedNexa, an AI receptionist for {hospital_name}.

HOSPITAL CONTEXT (auto-injected from DB):
- Address: {address}
- Timings: {opening_time} to {closing_time}
- Departments: {departments_list}
- Today's Date: {today}
- Current Time: {current_time}

ACTIVE DOCTORS TODAY:
{doctor_summaries_with_remaining_slots}

RULES:
1. Always be polite, professional, and concise.
2. Speak in the language the caller uses (English or Hindi). If uncertain, ask.
3. For booking: collect patient name, phone, age, gender, preferred doctor/speciality, preferred date/time.
4. For cancellation: verify caller by asking phone number + patient name before showing appointments.
5. NEVER reveal other patients' information.
6. If a slot is full, suggest the next available slot or an alternative doctor.
7. For questions you cannot answer, say you'll connect them with hospital staff.
8. Always confirm details before finalizing a booking or cancellation.
9. One call can handle multiple requests (book + cancel + info query).
```

---

## 4. Call Flow Pipeline

```
                     INCOMING CALL
                          │
                          ▼
                ┌─────────────────┐
                │   Asterisk PBX  │  (or Twilio webhook)
                │   answers call  │
                └────────┬────────┘
                         │ Audio stream (16kHz PCM)
                         ▼
                ┌─────────────────┐
                │  VAD (Silero)   │  Voice Activity Detection
                │  Detects speech │  — segments audio into utterances
                └────────┬────────┘
                         │ Audio chunks
                         ▼
                ┌─────────────────┐
                │  STT Engine     │  Faster-Whisper (local)
                │  Audio → Text   │  Model: large-v3 (multilingual)
                │                 │  Streaming mode for low latency
                └────────┬────────┘
                         │ Transcribed text + language tag
                         ▼
                ┌─────────────────┐
                │  AI Agent       │  LangGraph agent
                │  (LLM + Tools)  │  Processes text → calls tools → generates response
                │                 │  Maintains conversation state in memory
                └────────┬────────┘
                         │ Response text
                         ▼
                ┌─────────────────┐
                │  TTS Engine     │  Piper TTS (local) or Edge-TTS
                │  Text → Audio   │  Voice: Hindi female / English female
                │                 │  Streams audio back
                └────────┬────────┘
                         │ Audio stream
                         ▼
                ┌─────────────────┐
                │  Asterisk PBX   │  Plays audio to caller
                │  sends audio    │
                └─────────────────┘
```

### Latency Budget (Target: < 2s end-to-end)

| Stage | Target | Optimization |
|---|---|---|
| VAD | 50ms | Silero VAD — lightweight |
| STT | 300-500ms | Faster-Whisper with `beam_size=1`, FP16 |
| LLM | 500-1000ms | Local: quantized model; Cloud: Groq (fastest) |
| Tool execution | 50-100ms | SQLite in-memory / connection pool |
| TTS | 200-300ms | Piper ONNX, stream first chunk |
| **Total** | **~1.5-2s** | Pipelining: start TTS before full LLM response |

---

## 5. Five-Part Team Division

---

### PART 1 — Database, Models & API Layer
**Owner: Team Member 1 (Backend/DB Engineer)**

#### Scope
Everything related to data persistence, schema, migrations, and the REST API that both the AI agent and admin dashboard consume.

#### Deliverables

| # | Task | Priority | Est. Days |
|---|---|---|---|
| 1.1 | Set up project structure (Python, FastAPI, Poetry/uv) | P0 | 0.5 |
| 1.2 | Define SQLAlchemy 2.0 models for all entities (see schema above) | P0 | 1 |
| 1.3 | Alembic migration setup + initial migration | P0 | 0.5 |
| 1.4 | Seed data script (sample hospital, doctors, schedules) | P0 | 0.5 |
| 1.5 | CRUD API endpoints for Hospital, Doctor, Schedule, HospitalInfo | P0 | 2 |
| 1.6 | Appointment API — book, cancel, list, with business rule enforcement | P0 | 2 |
| 1.7 | Patient API — create/update, search by phone | P0 | 1 |
| 1.8 | Slot availability engine (compute free slots from schedule - booked) | P0 | 1.5 |
| 1.9 | Row-level locking for concurrent booking (SELECT FOR UPDATE) | P0 | 0.5 |
| 1.10 | Call session & log storage API | P1 | 1 |
| 1.11 | Database connection pooling & async session management | P0 | 0.5 |
| 1.12 | Unit tests for all business rules (pytest) | P0 | 2 |

#### Key Design Decisions

```python
# Slot computation pseudocode
def get_available_slots(doctor_id: UUID, date: date) -> list[TimeSlot]:
    doctor = db.get(Doctor, doctor_id)
    schedule = db.query(Schedule).filter(doctor_id=doctor_id, date=date).first()
    
    if not schedule or not schedule.is_available:
        return []
    
    # Generate all possible slots
    all_slots = generate_time_slots(
        start=schedule.start_time or doctor.slot_start_time,
        end=schedule.end_time or doctor.slot_end_time,
        duration=doctor.slot_duration_minutes
    )
    
    # Remove booked slots
    booked = db.query(Appointment).filter(
        doctor_id=doctor_id,
        appointment_date=date,
        status='BOOKED'
    ).all()
    booked_times = {appt.appointment_time for appt in booked}
    
    # Check max daily cap
    if len(booked) >= doctor.max_daily_appointments:
        return []
    
    return [s for s in all_slots if s.time not in booked_times]
```

#### Directory Structure

```
mednexa/
├── alembic/                    # DB migrations
│   ├── versions/
│   └── env.py
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app entry point
│   ├── config.py               # Settings (pydantic-settings)
│   ├── database.py             # Engine, session factory
│   ├── models/                 # SQLAlchemy models
│   │   ├── __init__.py
│   │   ├── hospital.py
│   │   ├── doctor.py
│   │   ├── schedule.py
│   │   ├── patient.py
│   │   ├── appointment.py
│   │   ├── hospital_info.py
│   │   └── call_log.py
│   ├── schemas/                # Pydantic request/response schemas
│   │   ├── __init__.py
│   │   ├── hospital.py
│   │   ├── doctor.py
│   │   ├── appointment.py
│   │   └── patient.py
│   ├── api/                    # API route handlers
│   │   ├── __init__.py
│   │   ├── v1/
│   │   │   ├── hospitals.py
│   │   │   ├── doctors.py
│   │   │   ├── appointments.py
│   │   │   ├── patients.py
│   │   │   ├── schedules.py
│   │   │   └── hospital_info.py
│   │   └── router.py
│   ├── services/               # Business logic layer
│   │   ├── __init__.py
│   │   ├── appointment_service.py
│   │   ├── slot_service.py
│   │   ├── patient_service.py
│   │   └── hospital_service.py
│   └── utils/
│       ├── exceptions.py
│       └── validators.py
├── tests/
│   ├── conftest.py
│   ├── test_appointments.py
│   ├── test_slots.py
│   └── test_business_rules.py
├── alembic.ini
├── pyproject.toml
└── .env.example
```

---

### PART 2 — AI Agent Core (LLM + Tool Calling)
**Owner: Team Member 2 (AI/ML Engineer)**

#### Scope
The brain of the system — the LangGraph-based agent that understands caller intent, maintains conversation state, calls the right tools, and generates natural responses in English or Hindi.

#### Deliverables

| # | Task | Priority | Est. Days |
|---|---|---|---|
| 2.1 | Set up Ollama with `llama3.1:8b` and `mistral-nemo:12b` locally | P0 | 0.5 |
| 2.2 | Build `ModelRouter` — unified LLM interface (local + cloud) | P0 | 1.5 |
| 2.3 | Implement latency monitoring + auto-fallback circuit breaker | P1 | 1 |
| 2.4 | Define all tool functions (Python callables wrapping Part 1's service layer) | P0 | 2 |
| 2.5 | Build LangGraph agent graph (state machine from §3) | P0 | 3 |
| 2.6 | System prompt engineering — dynamic context injection from DB | P0 | 1.5 |
| 2.7 | Language detection + bilingual response generation | P0 | 1 |
| 2.8 | Conversation memory management (per-call session) | P0 | 1 |
| 2.9 | Identity verification flow (phone + name matching) | P0 | 1 |
| 2.10 | Hallucination guardrails (output validation, tool-result grounding) | P1 | 1.5 |
| 2.11 | Multi-turn booking flow with slot negotiation | P0 | 2 |
| 2.12 | Edge case handling (no slots, invalid dates, past dates, etc.) | P0 | 1 |
| 2.13 | Agent evaluation harness (scripted test conversations) | P1 | 2 |

#### Key Architecture

```python
# LangGraph Agent Structure
from langgraph.graph import StateGraph, MessagesState
from langgraph.prebuilt import ToolNode

class MedNexaState(MessagesState):
    """Extended state for the receptionist agent."""
    language: str = "en"                    # detected language
    caller_phone: str = ""                  # from telephony
    verified_patient_id: Optional[str] = None
    current_intent: Optional[str] = None
    hospital_context: str = ""              # injected from DB
    booking_draft: Optional[dict] = None    # partial booking info

def build_agent_graph(tools: list, llm) -> StateGraph:
    graph = StateGraph(MedNexaState)
    
    # Nodes
    graph.add_node("agent", agent_node)          # LLM reasoning
    graph.add_node("tools", ToolNode(tools))      # Tool execution
    graph.add_node("guardrail", guardrail_node)   # Output validation
    
    # Edges
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_call_tool, {
        "tools": "tools",
        "guardrail": "guardrail",
    })
    graph.add_edge("tools", "agent")              # Tool result → back to LLM
    graph.add_edge("guardrail", END)
    
    return graph.compile(checkpointer=MemorySaver())
```

#### Model Router Design

```python
class ModelRouter:
    def __init__(self, config: ModelConfig):
        self.local_client = OllamaClient(model=config.local_model)
        self.cloud_client = GroqClient(model=config.cloud_model)  # or OpenAI
        self.failure_count = 0
        self.circuit_open_until = None
    
    async def invoke(self, messages, tools=None) -> LLMResponse:
        if self._should_use_cloud():
            return await self._cloud_invoke(messages, tools)
        
        try:
            start = time.monotonic()
            response = await self.local_client.invoke(messages, tools)
            latency = time.monotonic() - start
            
            if latency > self.config.max_latency_seconds:
                logger.warning(f"Local LLM slow: {latency:.2f}s, switching to cloud")
                self.failure_count += 1
                return await self._cloud_invoke(messages, tools)
            
            self.failure_count = 0
            return response
        except Exception as e:
            self.failure_count += 1
            if self.failure_count >= 3:
                self.circuit_open_until = time.monotonic() + 300  # 5 min
            return await self._cloud_invoke(messages, tools)
```

---

### PART 3 — Voice/Telephony Pipeline (STT + TTS + Call Management)
**Owner: Team Member 3 (Voice/Telephony Engineer)**

#### Scope
The audio pipeline — connecting phone calls to the AI agent. Handles speech-to-text, text-to-speech, voice activity detection, and integration with PBX or cloud telephony.

#### Deliverables

| # | Task | Priority | Est. Days |
|---|---|---|---|
| 3.1 | Set up Asterisk PBX with SIP trunk (or Twilio webhook for prototype) | P0 | 2 |
| 3.2 | Audio stream handler — WebSocket bridge between PBX and Python | P0 | 2 |
| 3.3 | VAD integration (Silero VAD) — detect speech start/end | P0 | 1 |
| 3.4 | Faster-Whisper STT integration — streaming transcription | P0 | 2 |
| 3.5 | Language detection from STT output (Hindi vs English) | P0 | 0.5 |
| 3.6 | Piper TTS integration — text-to-speech with Hindi + English voices | P0 | 1.5 |
| 3.7 | Edge-TTS fallback (cloud, free) | P1 | 0.5 |
| 3.8 | Audio streaming — play TTS output back to caller in real-time | P0 | 1.5 |
| 3.9 | Barge-in detection — stop TTS when caller starts speaking | P1 | 1 |
| 3.10 | Call session management (start, end, timeout handling) | P0 | 1 |
| 3.11 | DTMF fallback for menu navigation | P2 | 1 |
| 3.12 | Audio quality optimization (noise suppression, gain control) | P1 | 1 |
| 3.13 | Call recording & logging (with consent prompt) | P1 | 1 |
| 3.14 | Load testing — concurrent call handling | P1 | 1 |

#### Pipeline Architecture

```python
class CallPipeline:
    """Orchestrates the full call flow for a single call."""
    
    def __init__(self, call_id: str, caller_phone: str):
        self.call_id = call_id
        self.caller_phone = caller_phone
        self.vad = SileroVAD(threshold=0.5)
        self.stt = FasterWhisperSTT(model="large-v3", device="cuda")
        self.tts = PiperTTS(voices={"en": "en_US-amy", "hi": "hi_IN-swara"})
        self.agent = MedNexaAgent(caller_phone=caller_phone)
        self.language = "en"  # default, updated by STT
    
    async def handle_call(self, audio_stream: AsyncIterator[bytes]):
        # Play greeting
        greeting = await self.agent.get_greeting()
        await self.play_tts(greeting)
        
        async for audio_chunk in audio_stream:
            # 1. VAD — is someone speaking?
            if not self.vad.is_speech(audio_chunk):
                continue
            
            # 2. Accumulate speech until silence
            utterance = await self.collect_utterance(audio_chunk, audio_stream)
            
            # 3. STT — transcribe
            text, lang = await self.stt.transcribe(utterance)
            self.language = lang
            
            # 4. Agent — process
            response = await self.agent.process(text)
            
            # 5. TTS — speak response
            await self.play_tts(response, language=self.language)
    
    async def play_tts(self, text: str, language: str = "en"):
        audio_chunks = self.tts.synthesize_stream(text, voice=language)
        async for chunk in audio_chunks:
            await self.send_audio_to_caller(chunk)
```

#### Telephony Options Comparison

| Feature | Asterisk (Local) | Twilio (Cloud) |
|---|---|---|
| Cost | Free (OSS) | Per-minute billing |
| Setup complexity | High (SIP config) | Low (webhook URL) |
| Latency | Lowest (local) | +50-100ms network |
| Concurrent calls | Limited by hardware | Scales automatically |
| Hindi phone numbers | Need local SIP provider | Supports Indian numbers |
| **Recommendation** | Production | Prototype / MVP |

> [!TIP]
> **Start with Twilio for rapid prototyping**, then migrate to Asterisk for production to eliminate per-call costs. The `CallPipeline` abstraction makes switching easy.

---

### PART 4 — Admin Dashboard (Hospital Management UI)
**Owner: Team Member 4 (Frontend Engineer)**

#### Scope
Web-based admin dashboard where hospital staff manage doctors, schedules, appointments, hospital info, and monitor AI call activity.

#### Deliverables

| # | Task | Priority | Est. Days |
|---|---|---|---|
| 4.1 | Next.js 14 project setup with App Router | P0 | 0.5 |
| 4.2 | Authentication system (NextAuth.js — email/password for hospital staff) | P0 | 1.5 |
| 4.3 | Dashboard home — today's stats (appointments, calls, active doctors) | P0 | 1.5 |
| 4.4 | Doctor management — CRUD, profile, photo upload | P0 | 2 |
| 4.5 | Schedule management — weekly calendar view, bulk schedule, overrides | P0 | 2.5 |
| 4.6 | Appointment management — list, filter, manual book/cancel | P0 | 2 |
| 4.7 | Patient directory — search, view history | P1 | 1.5 |
| 4.8 | Hospital info management — FAQ-style entries the AI reads | P0 | 1 |
| 4.9 | Hospital settings — address, timings, logo, languages | P0 | 1 |
| 4.10 | Call logs viewer — transcripts, outcomes, escalations | P1 | 1.5 |
| 4.11 | Real-time active calls monitor (WebSocket) | P2 | 1.5 |
| 4.12 | Analytics — booking trends, peak hours, popular doctors | P2 | 2 |
| 4.13 | Responsive design + dark mode | P1 | 1.5 |

#### Dashboard Pages

```
/dashboard
├── /                           # Overview: today's stats, upcoming appointments
├── /doctors                    # List all doctors
│   ├── /new                    # Add new doctor
│   └── /[id]                   # Edit doctor details
│       └── /schedule           # Manage this doctor's weekly schedule
├── /appointments               # All appointments (filterable by date, doctor, status)
│   └── /[id]                   # Appointment details
├── /patients                   # Patient directory
│   └── /[id]                   # Patient history
├── /hospital-info              # Manage FAQ/info entries
├── /call-logs                  # View AI call transcripts
│   └── /[id]                   # Full call transcript
├── /settings                   # Hospital settings
└── /analytics                  # Charts and insights
```

#### UI Components (Key Screens)

**Dashboard Home:**
```
┌─────────────────────────────────────────────────────────┐
│  MedNexa Admin                         [Dr. Admin ▾]    │
├──────────┬──────────────────────────────────────────────┤
│          │  📊 Today's Overview          Oct 25, 2026   │
│ 🏠 Home  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐       │
│ 👨‍⚕️ Doctors│  │  24  │ │  18  │ │   3  │ │   6  │       │
│ 📅 Appts │  │Total │ │Booked│ │Cancel│ │ Open │       │
│ 👤 Patients│ └──────┘ └──────┘ └──────┘ └──────┘       │
│ ℹ️ Info   │                                             │
│ 📞 Calls │  Upcoming Appointments                       │
│ ⚙️ Settings│ ┌─────────────────────────────────────┐    │
│ 📈 Analytics│ │ 10:00  Dr. Sharma  Rahul K.  Booked │    │
│          │  │ 10:30  Dr. Patel   Priya S.   Booked │    │
│          │  │ 11:00  Dr. Sharma  —           Open   │    │
│          │  └─────────────────────────────────────┘     │
└──────────┴──────────────────────────────────────────────┘
```

---

### PART 5 — Integration, Security & DevOps
**Owner: Team Member 5 (DevOps/Integration Engineer)**

#### Scope
Gluing everything together, security hardening, deployment pipeline, monitoring, and ensuring the system runs reliably on a local hospital machine.

#### Deliverables

| # | Task | Priority | Est. Days |
|---|---|---|---|
| 5.1 | Docker Compose — all services (API, DB, Redis, Ollama, Asterisk) | P0 | 2 |
| 5.2 | Environment configuration management (.env, secrets) | P0 | 0.5 |
| 5.3 | API authentication — JWT for admin dashboard | P0 | 1 |
| 5.4 | Rate limiting on public APIs | P1 | 0.5 |
| 5.5 | CORS configuration | P0 | 0.5 |
| 5.6 | Data encryption at rest (SQLite encryption / PG SSL) | P1 | 1 |
| 5.7 | Caller identity verification module (phone + name; OTP later) | P0 | 1 |
| 5.8 | Integration testing — full call simulation (audio → STT → Agent → TTS) | P0 | 2 |
| 5.9 | Logging infrastructure (structured JSON logs, log rotation) | P0 | 1 |
| 5.10 | Health check endpoints + system monitoring | P1 | 1 |
| 5.11 | Auto-restart on crash (systemd / Docker restart policies) | P0 | 0.5 |
| 5.12 | Backup & restore scripts for database | P1 | 1 |
| 5.13 | GPU resource management (shared between Whisper + LLM + TTS) | P0 | 1 |
| 5.14 | Performance profiling & optimization | P1 | 1.5 |
| 5.15 | Documentation — setup guide, API docs, runbook | P0 | 2 |
| 5.16 | HIPAA/data privacy compliance review | P1 | 1 |

#### Docker Compose Layout

```yaml
version: '3.8'
services:
  # --- Core Services ---
  api:
    build: ./backend
    ports: ["8000:8000"]
    depends_on: [db, redis, ollama]
    environment:
      - DATABASE_URL=postgresql://mednexa:secret@db:5432/mednexa
      - REDIS_URL=redis://redis:6379
      - OLLAMA_URL=http://ollama:11434
    volumes:
      - ./data:/app/data
    restart: unless-stopped

  dashboard:
    build: ./dashboard
    ports: ["3000:3000"]
    depends_on: [api]
    environment:
      - API_URL=http://api:8000
    restart: unless-stopped

  # --- Data Layer ---
  db:
    image: postgres:16-alpine
    volumes: [pgdata:/var/lib/postgresql/data]
    environment:
      - POSTGRES_DB=mednexa
      - POSTGRES_USER=mednexa
      - POSTGRES_PASSWORD=secret
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    restart: unless-stopped

  # --- AI Services ---
  ollama:
    image: ollama/ollama
    ports: ["11434:11434"]
    volumes: [ollama_models:/root/.ollama]
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]
    restart: unless-stopped

  # --- Telephony ---
  asterisk:
    build: ./telephony
    ports:
      - "5060:5060/udp"   # SIP
      - "8088:8088"       # ARI WebSocket
    depends_on: [api]
    restart: unless-stopped

volumes:
  pgdata:
  ollama_models:
```

#### Security Architecture

```
┌─────────────────────────────────────────────────┐
│                SECURITY LAYERS                   │
├─────────────────────────────────────────────────┤
│                                                  │
│  1. NETWORK                                      │
│     ├── All services on internal Docker network   │
│     ├── Only ports 3000, 5060 exposed externally  │
│     └── HTTPS via reverse proxy (Caddy/Nginx)    │
│                                                  │
│  2. AUTHENTICATION                               │
│     ├── Admin dashboard: JWT + refresh tokens    │
│     ├── API: Bearer token auth                   │
│     └── Caller verification: phone + name match  │
│                                                  │
│  3. DATA PRIVACY                                 │
│     ├── Patient data never in LLM system prompt  │
│     │   (fetched via tools, per-call only)        │
│     ├── Call recordings encrypted at rest         │
│     ├── Logs redact phone numbers after 4 digits  │
│     └── Auto-purge call logs after 90 days       │
│                                                  │
│  4. AI SAFETY                                    │
│     ├── Tool outputs validated before LLM sees    │
│     ├── LLM cannot execute arbitrary DB queries   │
│     ├── Output guardrails: no medical advice      │
│     └── Escalation to human on low confidence    │
│                                                  │
└─────────────────────────────────────────────────┘
```

---

## 6. Phased Rollout Plan

### Phase 1 — Foundation (Week 1-3)
- [x] Database schema + migrations
- [x] Core API endpoints (CRUD for all entities)
- [x] Slot availability engine
- [x] Basic AI agent with tool calling (text-only, no voice)
- [x] Admin dashboard scaffold with doctor/schedule management

### Phase 2 — Voice Integration (Week 3-5)
- [ ] STT pipeline (Faster-Whisper)
- [ ] TTS pipeline (Piper + Edge-TTS fallback)
- [ ] Full call pipeline (audio → text → agent → audio)
- [ ] Twilio prototype for phone call testing
- [ ] Hindi language support

### Phase 3 — Production Hardening (Week 5-7)
- [ ] Asterisk PBX setup for local telephony
- [ ] Concurrent call handling
- [ ] Identity verification flow
- [ ] Call logging & analytics
- [ ] Docker Compose deployment
- [ ] Security audit

### Phase 4 — Polish & Scale (Week 7-9)
- [ ] Human handoff escalation (P2)
- [ ] SMS appointment confirmations
- [ ] Appointment reminders (Celery tasks)
- [ ] Analytics dashboard
- [ ] Performance optimization
- [ ] Documentation & training

---

## 7. Hardware Requirements (Hospital Local Server)

| Component | Minimum | Recommended |
|---|---|---|
| CPU | 8-core (i7/Ryzen 7) | 12+ core (i9/Ryzen 9) |
| RAM | 16 GB | 32 GB |
| GPU | NVIDIA RTX 3060 (12GB VRAM) | NVIDIA RTX 4070+ (12GB+ VRAM) |
| Storage | 256 GB SSD | 512 GB NVMe SSD |
| Network | 10 Mbps (for SIP) | 100 Mbps |
| OS | Ubuntu 22.04 LTS / Windows 11 | Ubuntu 22.04 LTS |

### GPU Memory Allocation

| Model | VRAM Usage | Notes |
|---|---|---|
| Faster-Whisper large-v3 | ~3 GB | Runs on GPU for speed |
| Ollama llama3.1:8b (Q4) | ~5 GB | Quantized for 8GB fit |
| Piper TTS | ~200 MB | ONNX, mostly CPU |
| **Total** | **~8-9 GB** | Fits in 12GB GPU |

---

## 8. Key Engineering Best Practices

| Practice | Implementation |
|---|---|
| **Repository Structure** | Monorepo with `backend/`, `dashboard/`, `telephony/`, `docker/` |
| **API Versioning** | `/api/v1/` prefix, backward-compatible changes |
| **Error Handling** | Custom exception classes, structured error responses |
| **Logging** | Structured JSON logging (structlog), correlation IDs per call |
| **Testing** | pytest (unit + integration), 80%+ coverage target |
| **CI/CD** | GitHub Actions — lint, test, build Docker images |
| **Code Quality** | Ruff (linting), Black (formatting), mypy (type checking) |
| **DB Migrations** | Alembic — never manual schema changes |
| **Secrets** | `.env` files, never committed; Docker secrets in production |
| **Monitoring** | Health checks, Prometheus metrics, Grafana dashboards |
| **Documentation** | OpenAPI (auto-generated), README per module, ADR for decisions |
| **Git Workflow** | Feature branches, PR reviews, conventional commits |

---

> [!IMPORTANT]
> ### First Steps to Begin Development
> 1. **Team Member 1** starts immediately — schema and API are the foundation everything else depends on
> 2. **Team Member 2** starts in parallel — can build agent with mock data while DB is being built
> 3. **Team Member 4** starts in parallel — dashboard scaffolding is independent
> 4. **Team Member 3** starts in Week 2 — needs API and agent ready to connect to
> 5. **Team Member 5** starts in Week 1 — Docker setup unblocks everyone, then focuses on integration in Week 3+

> [!NOTE]
> ### Local vs Cloud LLM Decision Criteria
> - **Use Local** if: hospital has RTX 3060+, latency < 3s, English-only or simple Hindi
> - **Use Cloud (Groq/OpenAI)** if: no GPU, latency > 3s, complex Hindi conversations, higher accuracy needed
> - **Hybrid** (recommended): Local for simple queries, cloud for complex conversations — `ModelRouter` handles this automatically
