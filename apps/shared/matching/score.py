"""Scoring formula: hard filters already passed, now compute a score
and a frozen reasons[] array."""

from datetime import datetime, timezone

from apps.shared.enums import PosterRole
from apps.shared.geo.yandex import route_minutes
from apps.shared.matching import config as cfg
from apps.shared.matching.reasons import ScoreComponents, build_reasons


def cosine_normalized(raw: float) -> float:
    """Map raw cosine [-1, 1] to [0, 1]."""
    return max(0.0, min(1.0, (1.0 + raw) / 2.0))


def _cosine_raw(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def budget_score(price: int | None, lo: int | None, hi: int | None) -> float:
    if price is None or hi is None or hi == 0:
        return 0.5
    if price <= hi:
        return 1.0
    if price >= hi * 1.5:
        return 0.0
    return 1.0 - (price - hi) / (hi * 0.5)


def commute_score(minutes: int | None, max_minutes: int | None) -> float:
    if minutes is None or max_minutes is None or max_minutes == 0:
        return 0.5
    if minutes <= max_minutes:
        return 1.0
    if minutes >= max_minutes * 1.5:
        return 0.0
    return 1.0 - (minutes - max_minutes) / (max_minutes * 0.5)


def freshness_score(posted_at: datetime | None) -> float:
    if posted_at is None:
        return 0.5
    now = datetime.now(timezone.utc)
    age_days = max(0.0, (now - posted_at).total_seconds() / 86400.0)
    return 0.5 ** (age_days / 14.0)


def _source_rep(listing) -> float:
    if listing.poster_role == PosterRole.OWNER:
        return 1.0
    if listing.poster_role == PosterRole.AGENT:
        return 0.7
    return 0.5


def _axis_bonus(user, listing) -> float:
    """Fraction of NICE axes satisfied. Skipped axes don't count."""
    prio = user.axis_priority or {}
    satisfied = 0
    counted = 0
    for axis, priority in prio.items():
        if priority != "NICE":
            continue
        if axis == "budget":
            if user.budget_max and listing.price_uzs and listing.price_uzs <= user.budget_max:
                satisfied += 1
            counted += 1
        elif axis == "area":
            if user.areas and listing.area in (user.areas or []):
                satisfied += 1
            counted += 1
        elif axis == "rooms":
            if user.rooms is not None and listing.rooms == user.rooms:
                satisfied += 1
            counted += 1
        # commute and furnishing skipped: unmeasured or no user-side column
    if counted == 0:
        return 0.5
    return satisfied / counted


def score_listing_for_user(user, listing) -> tuple[float, list[str], ScoreComponents]:
    """Compute (score, reasons, components) for a (user, listing) pair.

    Assumes hard filters have already passed.
    """
    components = ScoreComponents()
    components.cosine = cosine_normalized(
        _cosine_raw(user.preference_embedding or [], listing.embedding or [])
    )
    components.budget_score = budget_score(listing.price_uzs, user.budget_min, user.budget_max)
    components.freshness = freshness_score(listing.posted_at)
    components.source_rep = _source_rep(listing)
    components.axis_bonus = _axis_bonus(user, listing)
    components.risk_penalty = min(3, getattr(listing, "risk_score", 0) or 0)

    commute_used = False
    if (
        user.commute_origin_lat is not None
        and user.commute_origin_lng is not None
        and listing.lat is not None
        and listing.lng is not None
    ):
        mins = route_minutes(
            user.commute_origin_lat, user.commute_origin_lng,
            listing.lat, listing.lng,
            mode=user.commute_mode or "car",
        )
        components.commute_minutes = mins
        components.commute = commute_score(mins, user.commute_max_minutes)
        commute_used = True

    score = (
        cfg.W_COSINE * components.cosine
        + cfg.W_FRESHNESS * components.freshness
        + cfg.W_SOURCE_REP * components.source_rep
        + cfg.W_AXIS_BONUS * components.axis_bonus
        - cfg.W_RISK * (components.risk_penalty / 3.0)
    )

    prio = user.axis_priority or {}
    if prio.get("budget") == "NICE":
        score += cfg.W_BUDGET * components.budget_score
    if commute_used:
        score += cfg.W_COMMUTE * (components.commute or 0.5)

    reasons = build_reasons(user, listing, components)
    return score, reasons, components
