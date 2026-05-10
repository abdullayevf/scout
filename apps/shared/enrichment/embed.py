def build_listing_embedding_text(
    *,
    title: str,
    description_ru: str,
    summary_one_line: str | None,
    rooms: int | None,
    area: str | None,
    price_uzs: int | None,
    is_furnished: bool | None,
    has_parking: bool | None,
    bathroom_type: str | None,
) -> str:
    parts = [title, description_ru, summary_one_line or ""]
    structured = []
    if rooms is not None:
        structured.append(f"rooms={rooms}")
    if area:
        structured.append(f"area={area}")
    if price_uzs is not None:
        structured.append(f"price_uzs={price_uzs}")
    if is_furnished:
        structured.append("furnished")
    if has_parking:
        structured.append("parking")
    if bathroom_type and bathroom_type != "unknown":
        structured.append(f"bathroom={bathroom_type}")
    parts.append(" ".join(structured))
    return "\n".join(p for p in parts if p)


def embed_listing(text: str, *, llm) -> list[float]:
    return llm.embed(text)
