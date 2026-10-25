"""The service contract for Part 2's agent tools.

Agent @tool functions wrap exactly these functions and nothing else. Each takes
an AsyncSession as its first argument. `hospital_id` and `caller_phone` must come
from the call state (telephony), never from the LLM.

Every function raises only `app.core.exceptions.DomainError` subclasses for
expected failures; read `exc.code` / `exc.message` and phrase it for the caller:

    not_found, validation_error, invalid_slot, slot_unavailable,
    daily_cap_reached, duplicate_booking, not_owner, not_cancellable, conflict

Write functions commit their own transaction. Changing a signature here needs
agreement with Part 2.
"""

from app.services.appointment_service import (
    book_appointment,
    cancel_appointment,
    get_patient_appointments,
    reschedule_appointment,
)
from app.services.doctor_service import get_doctor, list_doctors
from app.services.hospital_service import get_hospital_info
from app.services.slot_service import find_next_available, get_available_slots

__all__ = [
    "book_appointment",
    "cancel_appointment",
    "find_next_available",
    "get_available_slots",
    "get_doctor",
    "get_hospital_info",
    "get_patient_appointments",
    "list_doctors",
    "reschedule_appointment",
]
