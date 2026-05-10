from apps.shared.enrichment.language import detect_language


def test_detects_russian():
    assert detect_language("Двухкомнатная квартира в центре, мебель есть.") == "ru"


def test_detects_uzbek_latin():
    txt = "Ikki xonali kvartira shahar markazida, mebel bilan."
    assert detect_language(txt) == "uz-latn"


def test_detects_uzbek_cyrillic():
    txt = "Икки хонали квартира марказда, мебель билан."
    assert detect_language(txt) == "uz-cyrl"


def test_short_text_falls_back_to_unknown_or_ru():
    assert detect_language("ok") in ("unknown", "ru")
