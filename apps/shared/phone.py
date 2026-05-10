import hashlib
import re

_DIGITS_ONLY = re.compile(r"\D+")


def normalize_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = _DIGITS_ONLY.sub("", raw)
    if not digits:
        return None
    # Common UZ prefixes:
    if digits.startswith("998"):
        pass
    elif digits.startswith("8") and len(digits) == 10:
        digits = "998" + digits[1:]
    elif len(digits) == 9:
        digits = "998" + digits
    if len(digits) != 12 or not digits.startswith("998"):
        return None
    return digits


def hash_phone(normalized: str) -> str:
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
