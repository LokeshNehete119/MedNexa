import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import CallOutcome, CallRole
from app.schemas.common import ORMModel, Phone


class CallSessionCreate(BaseModel):
    hospital_id: uuid.UUID
    caller_phone: Phone
    language_detected: str | None = Field(default=None, max_length=10)


class CallLogCreate(BaseModel):
    role: CallRole
    content: str
    tool_called: str | None = Field(default=None, max_length=100)
    tool_result: str | None = None
    appointment_id: uuid.UUID | None = None


class CallSessionEnd(BaseModel):
    call_outcome: CallOutcome
    summary: str | None = None
    language_detected: str | None = Field(default=None, max_length=10)
    escalated_to_human: bool = False


class CallLogOut(ORMModel):
    id: uuid.UUID
    session_id: uuid.UUID
    appointment_id: uuid.UUID | None
    role: CallRole
    content: str
    tool_called: str | None
    tool_result: str | None
    timestamp: datetime


class CallSessionOut(ORMModel):
    id: uuid.UUID
    hospital_id: uuid.UUID
    caller_phone: str
    call_start: datetime
    call_end: datetime | None
    language_detected: str | None
    call_outcome: CallOutcome | None
    summary: str | None
    escalated_to_human: bool
    total_turns: int


class CallSessionDetailOut(CallSessionOut):
    logs: list[CallLogOut]
