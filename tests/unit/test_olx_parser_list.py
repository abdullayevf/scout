from pathlib import Path

from apps.shared.scraping.olx_parser import parse_list_page

FIXTURE = Path(__file__).parent.parent / "fixtures" / "olx_list_long_term.html"


def test_parse_list_extracts_at_least_one_card():
    html = FIXTURE.read_text(encoding="utf-8")
    cards = parse_list_page(html)
    assert len(cards) >= 1
    first = cards[0]
    assert first.url.startswith("https://www.olx.uz/")
    assert first.source_listing_id  # non-empty string
    assert first.title


def test_parse_list_card_has_price_or_none():
    html = FIXTURE.read_text(encoding="utf-8")
    cards = parse_list_page(html)
    # at least one card has a parseable price; some may have "договорная" / no price
    parseable = [c for c in cards if c.price_raw is not None]
    assert len(parseable) >= 1
