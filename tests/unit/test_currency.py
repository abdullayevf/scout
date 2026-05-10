from pathlib import Path
from unittest.mock import MagicMock, patch

import respx
from httpx import Response

from apps.shared.enrichment.currency import (
    convert_to_uzs,
    fetch_cbu_usd_to_uzs,
    parse_price_text,
)


def test_parse_price_uzs():
    p, c = parse_price_text("8 000 000 \u0441\u0443\u043c")  # sum (Cyrillic)
    assert p == 8_000_000 and c == "UZS"


def test_parse_price_usd():
    p, c = parse_price_text("$650")
    assert p == 650 and c == "USD"


def test_parse_price_with_thousand_separators():
    # u.e. written in Cyrillic as u+0443 . u+0435
    p, c = parse_price_text("1 200 \u0443.\u0435.")
    assert p == 1200 and c == "USD"


def test_parse_price_returns_none_on_garbage():
    assert parse_price_text("\u0434\u043e\u0433\u043e\u0432\u043e\u0440\u043d\u0430\u044f") == (None, None)


@respx.mock
def test_fetch_cbu_returns_float(monkeypatch):
    fixture = Path("tests/fixtures/cbu_rate.json").read_text(encoding="utf-8")
    respx.get("https://cbu.uz/uz/arkhiv-kursov-valyut/json/USD/").mock(
        return_value=Response(200, text=fixture)
    )
    # Patch session_scope so no real DB is needed
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.execute.return_value.scalar_one_or_none.return_value = None

    with patch("apps.shared.enrichment.currency.session_scope", return_value=mock_session):
        rate = fetch_cbu_usd_to_uzs()
    assert rate > 1000


def test_convert_uzs_passthrough():
    assert convert_to_uzs(1_000_000, "UZS", usd_rate=12500) == 1_000_000


def test_convert_usd_to_uzs():
    assert convert_to_uzs(500, "USD", usd_rate=12500) == 6_250_000
