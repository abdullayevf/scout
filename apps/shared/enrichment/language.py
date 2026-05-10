import re

# Uzbek-Latin morpheme markers (orthography + common rental words)
_UZ_LATN_HINTS = re.compile(
    r"[oʻgʻ'ʼ]|\b(xonali|kvartira|ijara(?:ga)?|markaz(?:da|ida)?|mebel|uy|narx)\b",  # noqa: RUF001
    re.IGNORECASE,
)
# Uzbek-Cyrillic morpheme markers (the Cyrillic letters ў/қ/ҳ/ғ are exclusive to Uzbek/etc, not Russian;
# plus typical rental/grammar words)
_UZ_CYRL_HINTS = re.compile(
    r"[ўқҳғ]|\b(хонали|ижара(?:га)?|узатилади|ижарага|марказ(?:да|ида)?|мебелсиз|нархи)\b",  # noqa: RUF001
    re.IGNORECASE,
)


def detect_language(text: str) -> str:
    """Returns one of: 'ru', 'uz-latn', 'uz-cyrl', 'unknown'."""
    if not text or len(text) < 6:
        return "unknown"

    has_cyrillic = bool(re.search(r"[Ѐ-ӿ]", text))
    has_latin = bool(re.search(r"[A-Za-z]", text))

    if has_cyrillic and not has_latin:
        return "uz-cyrl" if _UZ_CYRL_HINTS.search(text) else "ru"

    if has_latin and not has_cyrillic:
        # In Tashkent OLX domain, Latin-only listings are overwhelmingly Uzbek-Latin (rarely English).
        return "uz-latn"

    if has_cyrillic and has_latin:
        # Mixed: prefer Uzbek hint if any, otherwise dominant-script.
        if _UZ_CYRL_HINTS.search(text):
            return "uz-cyrl"
        if _UZ_LATN_HINTS.search(text):
            return "uz-latn"
        cyr = len(re.findall(r"[Ѐ-ӿ]", text))
        lat = len(re.findall(r"[A-Za-z]", text))
        return "ru" if cyr >= lat else "uz-latn"

    return "unknown"
