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


def build_user_pref_text(
    *,
    search_type: str | None,
    budget_min: int | None,
    budget_max: int | None,
    rooms: int | None,
    areas: list[str],
    commute_origin: str | None,
    commute_max_minutes: int | None,
    commute_mode: str | None,
    dealbreakers: list[str],
    tradeoff_hint_text: str | None,
    unacceptable_text: str | None,
) -> str:
    parts = []
    if search_type:
        parts.append(f"search_type={search_type}")
    if budget_min is not None:
        parts.append(f"budget_min={budget_min}")
    if budget_max is not None:
        parts.append(f"budget_max={budget_max}")
    if rooms is not None:
        parts.append(f"rooms={rooms}")
    if areas:
        parts.append("areas=" + ",".join(areas))
    if commute_origin:
        parts.append(f"commute_from={commute_origin}")
    if commute_max_minutes is not None:
        parts.append(f"commute_max={commute_max_minutes}min")
    if commute_mode:
        parts.append(f"commute_mode={commute_mode}")
    if dealbreakers:
        parts.append("dealbreakers=" + ",".join(dealbreakers))
    if tradeoff_hint_text:
        parts.append(tradeoff_hint_text)
    if unacceptable_text:
        parts.append(unacceptable_text)
    return "\n".join(parts)
