PHONE_UNRELATED_THRESHOLD = 3


def compute_risk(
    *,
    price_uzs: int | None,
    area_median: int | None,
    area_stdev: int | None,
    phone_seen_unrelated: int,
    cross_phash_collision: bool,
    agent_keywords_present: bool,
    poster_role: str,
) -> tuple[int, dict]:
    flags: dict[str, bool] = {}
    if (
        price_uzs is not None
        and area_median is not None
        and area_stdev is not None
        and price_uzs < (area_median - 2 * area_stdev)
    ):
        flags["unusually_low_price"] = True
    if phone_seen_unrelated >= PHONE_UNRELATED_THRESHOLD:
        flags["phone_seen_unrelated"] = True
    if cross_phash_collision:
        flags["photo_possibly_reused"] = True
    if agent_keywords_present and poster_role == "owner":
        flags["agent_keywords_with_owner_label"] = True
    return (sum(flags.values()), flags)
