"""Domain exceptions raised by the service layer.

Each carries a stable machine-readable `code`. The API maps them to HTTP errors
(see app/api/errors.py) and the agent tools (Part 2) turn them into short
messages the LLM can explain to the caller.
"""


class DomainError(Exception):
    code = "domain_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(DomainError):
    code = "not_found"


class DomainValidationError(DomainError):
    """The request is well-formed but breaks a business rule (inactive doctor, ...)."""

    code = "validation_error"


class InvalidSlot(DomainError):
    """The requested time is not a bookable slot (off day, outside hours, off-grid, past)."""

    code = "invalid_slot"


class SlotUnavailable(DomainError):
    """The slot exists but is already taken."""

    code = "slot_unavailable"


class DailyCapReached(DomainError):
    code = "daily_cap_reached"


class DuplicateBooking(DomainError):
    """The same patient already holds this exact slot."""

    code = "duplicate_booking"


class NotOwner(DomainError):
    """The caller's phone number does not match the appointment's patient."""

    code = "not_owner"


class NotCancellable(DomainError):
    """Only BOOKED appointments can be cancelled or rescheduled."""

    code = "not_cancellable"


class Conflict(DomainError):
    """A uniqueness rule other than slot booking was violated (e.g. duplicate patient)."""

    code = "conflict"
