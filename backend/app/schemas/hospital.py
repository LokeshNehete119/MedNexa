import uuid
from datetime import datetime, time

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.schemas.common import ORMModel, TimeZoneName


class HospitalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    address: str = Field(min_length=1)
    phone: str = Field(min_length=3, max_length=20)
    email: EmailStr | None = None
    opening_time: time
    closing_time: time
    timezone: TimeZoneName = "Asia/Kolkata"
    languages: list[str] = Field(default_factory=lambda: ["en", "hi"], min_length=1)
    general_instructions: str | None = None

    @model_validator(mode="after")
    def _hours_valid(self) -> "HospitalCreate":
        if self.closing_time <= self.opening_time:
            raise ValueError("closing_time must be after opening_time")
        return self


class HospitalUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    address: str | None = Field(default=None, min_length=1)
    phone: str | None = Field(default=None, min_length=3, max_length=20)
    email: EmailStr | None = None
    opening_time: time | None = None
    closing_time: time | None = None
    timezone: TimeZoneName | None = None
    languages: list[str] | None = Field(default=None, min_length=1)
    general_instructions: str | None = None
    is_active: bool | None = None


class HospitalOut(ORMModel):
    id: uuid.UUID
    name: str
    address: str
    phone: str
    email: str | None
    opening_time: time
    closing_time: time
    timezone: str
    languages: list[str]
    general_instructions: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class HospitalInfoCreate(BaseModel):
    category: str = Field(min_length=1, max_length=50)
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)


class HospitalInfoUpdate(BaseModel):
    category: str | None = Field(default=None, min_length=1, max_length=50)
    question: str | None = Field(default=None, min_length=1)
    answer: str | None = Field(default=None, min_length=1)
    is_active: bool | None = None


class HospitalInfoOut(ORMModel):
    id: uuid.UUID
    hospital_id: uuid.UUID
    category: str
    question: str
    answer: str
    is_active: bool
    updated_at: datetime
