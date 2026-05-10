from unittest.mock import MagicMock

from apps.shared.enrichment.embed import build_listing_embedding_text, embed_listing


def test_text_includes_title_and_summary():
    txt = build_listing_embedding_text(
        title="2-komn., Yunusabad",
        description_ru="Prostornaya dvushka s mebelyu.",
        summary_one_line="Dvushka s mebelyu.",
        rooms=2,
        area="Yunusabad",
        price_uzs=8_000_000,
        is_furnished=True,
        has_parking=False,
        bathroom_type="private",
    )
    assert "2-komn., Yunusabad" in txt
    assert "Prostornaya" in txt
    assert "rooms=2" in txt
    assert "furnished" in txt


def test_embed_listing_calls_llm():
    llm = MagicMock()
    llm.embed.return_value = [0.1] * 768
    out = embed_listing("any text", llm=llm)
    assert len(out) == 768
    llm.embed.assert_called_once_with("any text")
