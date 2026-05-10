import re
from datetime import datetime

import httpx
from sqlalchemy import select

from apps.shared.db import session_scope
from apps.shared.models import CurrencyRate

_PRICE_NUM = re.compile(r"([\d\s\xa0]+)")

# Uzbek/Russian currency text markers.
# Strings use literal Unicode escape sequences to satisfy ruff RUF001.
_USD_MARKERS = ("$", "\u0443.\u0435", "y.e", "usd")
_UZS_MARKERS = ("\u0441\u0443\u043c", "uzs", "so'm", "so\u02bcm")


def parse_price_text(text: str | None) -> tuple[int | None, str | None]:
    if not text:
        return (None, None)
    t = text.lower()
    if "\u0434\u043e\u0433\u043e\u0432\u043e\u0440" in t:  # dogovor
        return (None, None)
    currency: str | None = None
    if any(marker in t for marker in _USD_MARKERS):
        currency = "USD"
    elif any(marker in t for marker in _UZS_MARKERS):
        currency = "UZS"
    normalized = t.replace("\xa0", " ")
    m = _PRICE_NUM.search(normalized)
    if not m:
        return (None, currency)
    digits = re.sub(r"\D", "", m.group(1))
    if not digits:
        return (None, currency)
    return (int(digits), currency)


def fetch_cbu_usd_to_uzs() -> float:
    """Fetch and cache today's CBU USD->UZS rate. Returns rate."""
    today = datetime.now(tz=None).date()
    with session_scope() as s:
        row = s.execute(
            select(CurrencyRate)
            .where(CurrencyRate.code == "USD")
            .order_by(CurrencyRate.fetched_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if row and row.fetched_at.date() == today:
            return row.rate_uzs

    r = httpx.get(
        "https://cbu.uz/uz/arkhiv-kursov-valyut/json/USD/",
        timeout=10.0,
    )
    r.raise_for_status()
    data = r.json()
    rate = float(data[0]["Rate"])
    with session_scope() as s:
        s.add(CurrencyRate(code="USD", rate_uzs=rate))
    return rate


def convert_to_uzs(amount: int, currency: str, *, usd_rate: float) -> int:
    if currency == "UZS":
        return amount
    if currency == "USD":
        return round(amount * usd_rate)
    return amount
