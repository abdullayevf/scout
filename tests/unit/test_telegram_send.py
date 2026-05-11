from dataclasses import dataclass
from apps.shared.telegram_send import format_match_text

@dataclass
class _Listing:
    rooms: int | None = 2
    area: str | None = "Yunusabad"
    source_url: str = "https://www.olx.uz/x"
    summary_one_line: str | None = "балкон, рядом метро"

def test_format_match_text_basic():
    listing = _Listing()
    reasons = ["💰 1 400 000 UZS · в твоём бюджете", "🆕 12 мин назад", "📍 Юнусабад"]
    text = format_match_text(listing, reasons)
    assert "🏠 2-комн., Юнусабад" in text
    assert "💰 1 400 000 UZS" in text
    assert "балкон, рядом метро" in text
    assert "🔗 https://www.olx.uz/x" in text

def test_format_match_text_with_prefix():
    listing = _Listing()
    text = format_match_text(listing, reasons=["🆕 5 мин назад"], prefix="🔥 Свежий топ-вариант")
    assert text.splitlines()[0] == "🔥 Свежий топ-вариант"

def test_format_match_text_no_summary():
    listing = _Listing(summary_one_line=None)
    text = format_match_text(listing, reasons=["📍 Юнусабад"])
    assert "🏠" in text
    assert "🔗" in text
    assert "\n\n\n" not in text

def test_format_match_text_no_rooms():
    listing = _Listing(rooms=None)
    text = format_match_text(listing, reasons=[])
    assert "🏠 квартира, Юнусабад" in text
