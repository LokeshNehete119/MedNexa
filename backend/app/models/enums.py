from enum import StrEnum


class AppointmentStatus(StrEnum):
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    RESCHEDULED = "RESCHEDULED"


class BookingSource(StrEnum):
    AI_CALL = "AI_CALL"
    DASHBOARD = "DASHBOARD"
    WALK_IN = "WALK_IN"


class Gender(StrEnum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    OTHER = "OTHER"


class CallOutcome(StrEnum):
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"
    RESCHEDULED = "RESCHEDULED"
    INFO_PROVIDED = "INFO_PROVIDED"
    ESCALATED = "ESCALATED"
    ABANDONED = "ABANDONED"
    OTHER = "OTHER"


class CallRole(StrEnum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"
    TOOL = "TOOL"
    SYSTEM = "SYSTEM"
