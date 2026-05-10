import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import respx
from httpx import Response
from sqlalchemy.orm import sessionmaker

import apps.shared.db as db_module
from apps.shared.enums import ListingState
from apps.shared.models import Base, Listing
from apps.workers.tasks.enrich import _enrich_one


@respx.mock
def test_enrich_one_full_pipeline(engine, monkeypatch):
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    # redirect all session_scope() calls to the testcontainer engine
    db_module._engine = engine
    db_module.SessionLocal = SessionLocal

    monkeypatch.setenv("YANDEX_GEOCODE_API_KEY", "test")

    # seed a pending listing manually (skip the scrape step in this test)
    s = SessionLocal()
    detail_html = Path("tests/fixtures/olx_detail_owner.html").read_text(encoding="utf-8")  # noqa: F841
    classification = json.loads(Path("tests/fixtures/gemini_classify_owner.json").read_text())
    geo_fixture = Path("tests/fixtures/yandex_geocode_yunusabad.json").read_text()

    row = Listing(
        source="olx",
        source_url="https://www.olx.uz/d/obyavlenie/test-1",
        source_listing_id="test-1",
        source_category="long_term_apt",
        title="2-комн. в Юнусабаде",
        description_raw="Просторная двушка с мебелью, рядом метро Юнусабад.",  # noqa: RUF001
        price_raw="$650",
        location_text="Юнусабадский район",
        state=ListingState.PENDING_ENRICH,
        last_seen_at=datetime.now(UTC),
        image_urls=[],
        image_phashes=[],
    )
    s.add(row)
    s.commit()
    listing_id = row.id
    s.close()

    # mock external HTTP
    respx.get("https://geocode-maps.yandex.ru/1.x/").mock(return_value=Response(200, text=geo_fixture))
    respx.get("https://cbu.uz/uz/arkhiv-kursov-valyut/json/USD/").mock(
        return_value=Response(200, json=[{"Rate": "12500.0"}])
    )

    # mock Gemini at the SDK boundary
    with patch("apps.shared.llm.gemini.genai.Client") as MockClient, \
         patch("apps.shared.scraping.playwright_phone.async_playwright"):
        inst = MockClient.return_value
        # generate_content returns either translation, classification JSON, or summary;
        # one-call-per-method: we mock generate_content to return classification JSON,
        # translate_to_ru is bypassed because language detection will be 'ru'.
        inst.models.generate_content.return_value.text = json.dumps(classification)
        inst.models.embed_content.return_value.embeddings = [type("E", (), {"values": [0.1] * 768})()]

        out = _enrich_one(listing_id)

    assert out["ok"] is True

    s = SessionLocal()
    final = s.get(Listing, listing_id)
    assert final.state == ListingState.ACTIVE
    assert final.search_type_listing == classification["search_type"]
    assert final.price_uzs == 8_125_000  # 650 * 12500
    assert final.lat is not None
    assert final.embedding is not None
    s.close()
