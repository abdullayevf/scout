def ensure_ru(text: str, *, language: str, llm) -> str:
    if not text or len(text) < 8:
        return text
    if language == "ru":
        return text
    if language in ("uz-latn", "uz-cyrl"):
        return llm.translate_to_ru(text)
    return text
