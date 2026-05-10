from pathlib import Path

from apps.shared.scraping.olx_parser import parse_detail_page

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_parse_detail_owner():
    html = (FIXTURES / "olx_detail_owner.html").read_text(encoding="utf-8")
    d = parse_detail_page(html)
    assert d.title
    assert d.description_raw
    assert d.location_text
    assert d.images  # at least one image URL


def test_parse_detail_agent_keywords_in_description():
    html = (FIXTURES / "olx_detail_agent.html").read_text(encoding="utf-8")
    d = parse_detail_page(html)
    txt = (d.description_raw + " " + d.title).lower()
    # heuristic: agent listings often mention "посредник", "комиссия", "агент"
    assert any(kw in txt for kw in ("посредник", "комисси", "агент"))
