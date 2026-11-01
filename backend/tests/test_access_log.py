import logging

from app.main import MaskPhoneNumbersInAccessLog


def access_record(path: str) -> logging.LogRecord:
    args = ("127.0.0.1:5000", "GET", path, "1.1", 200)
    return logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "%s %s %s %s %d", args, None)


def test_phone_numbers_in_queries_are_masked() -> None:
    record = access_record("/api/v1/patients?phone=%2B919876543210&limit=20")
    assert MaskPhoneNumbersInAccessLog().filter(record)
    assert record.getMessage() == (
        "127.0.0.1:5000 GET /api/v1/patients?phone=%2B********3210&limit=20 1.1 200"
    )
    record = access_record("/api/v1/calls?hospital_id=1&caller_phone=9876543210")
    MaskPhoneNumbersInAccessLog().filter(record)
    assert "caller_phone=******3210" in record.getMessage()


def test_other_paths_are_unchanged() -> None:
    record = access_record("/api/v1/appointments?date=2026-10-31&limit=200")
    MaskPhoneNumbersInAccessLog().filter(record)
    assert "date=2026-10-31&limit=200" in record.getMessage()
