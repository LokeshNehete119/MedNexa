from typing import Annotated, Generic, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints

from app.core.normalize import clean_name, normalize_phone

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


def _valid_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown timezone: {value}") from exc
    return value


Phone = Annotated[str, AfterValidator(normalize_phone)]
PersonName = Annotated[
    str, StringConstraints(min_length=1, max_length=200), AfterValidator(clean_name)
]
TimeZoneName = Annotated[str, AfterValidator(_valid_timezone)]
