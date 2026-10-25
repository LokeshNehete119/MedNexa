import re

from app.config import get_settings

_NON_DIGITS = re.compile(r"\D")
_WHITESPACE = re.compile(r"\s+")


def normalize_phone(raw: str) -> str:
    """Canonical E.164-style phone: '+' followed by digits.

    "98765 43210", "098765-43210", "+91 98765 43210" and "919876543210" all become
    "+919876543210" (with the default country code 91). Ownership checks compare
    normalized values, so the same caller is always recognised.
    """
    raw = raw.strip()
    digits = _NON_DIGITS.sub("", raw)
    country = get_settings().default_country_code
    if raw.startswith("+"):
        result = digits
    elif len(digits) == 10:
        result = country + digits
    elif len(digits) == 11 and digits.startswith("0"):
        result = country + digits[1:]
    else:
        result = digits
    if not 8 <= len(result) <= 15:
        raise ValueError("invalid phone number")
    return "+" + result


def normalize_name(name: str) -> str:
    """Lower-cased, whitespace-collapsed name used for patient identity."""
    return _WHITESPACE.sub(" ", name).strip().casefold()


def clean_name(name: str) -> str:
    """Display form: trimmed, whitespace-collapsed, original casing kept."""
    return _WHITESPACE.sub(" ", name).strip()
