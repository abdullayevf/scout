from unittest.mock import MagicMock

from apps.shared.enrichment.translate import ensure_ru


def test_returns_text_as_is_when_already_ru():
    out = ensure_ru("Двухкомнатная квартира.", language="ru", llm=None)
    assert out == "Двухкомнатная квартира."


def test_calls_llm_for_uz_latn():
    llm = MagicMock()
    llm.translate_to_ru.return_value = "Двухкомнатная квартира."
    out = ensure_ru("Ikki xonali kvartira.", language="uz-latn", llm=llm)
    assert out == "Двухкомнатная квартира."
    llm.translate_to_ru.assert_called_once()


def test_short_text_skips_llm():
    llm = MagicMock()
    out = ensure_ru("ok", language="uz-latn", llm=llm)
    assert out == "ok"
    llm.translate_to_ru.assert_not_called()
