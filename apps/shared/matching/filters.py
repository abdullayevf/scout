"""Hard filters: SQL-side cheap pruning + Python-side per-listing checks."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.shared.enums import GenderConstraint, PosterRole, SearchType, UserState
from apps.shared.models import User


SEARCH_TYPE_COMPAT: dict[str, set[str]] = {
    SearchType.WHOLE_APT_FAMILY: {
        SearchType.WHOLE_APT_FAMILY,
        SearchType.WHOLE_APT_SOLO,
    },
    SearchType.WHOLE_APT_SOLO: {
        SearchType.WHOLE_APT_SOLO,
        SearchType.WHOLE_APT_FAMILY,
    },
    SearchType.SHARED_ROOM: {
        SearchType.SHARED_ROOM,
    },
    SearchType.LOOKING_FOR_ROOMMATE: {
        SearchType.LOOKING_FOR_ROOMMATE,
        SearchType.SHARED_ROOM,
    },
}


DEALBREAKER_MAP: dict[str, callable] = {
    "no_first_floor": lambda l: l.is_first_floor is False,
    "no_shared_bathroom": lambda l: l.bathroom_type != "shared",
    "must_have_parking": lambda l: l.has_parking is True,
}


def sql_filter_candidates(session: Session, listing) -> list[User]:
    """SQL-level cheap filters. Returns active User rows that could
    plausibly match this listing — caller must still apply Python-side
    filters (commute routing, dealbreakers, keywords, etc.)."""

    listing_st = listing.search_type_listing
    matching_user_types = [
        ust for ust, listing_set in SEARCH_TYPE_COMPAT.items()
        if listing_st in listing_set
    ]
    if not matching_user_types:
        return []

    stmt = (
        select(User)
        .where(User.state == UserState.ACTIVE)
        .where(User.search_type.in_(matching_user_types))
    )

    # Budget MUST gate
    if listing.price_uzs is not None:
        stmt = stmt.where(
            (User.axis_priority["budget"].astext == "NICE")
            | (
                (User.budget_min.is_(None) | (User.budget_min <= listing.price_uzs))
                & (User.budget_max.is_(None) | (User.budget_max >= listing.price_uzs))
            )
        )

    # Agent filter
    if listing.poster_role == PosterRole.AGENT:
        stmt = stmt.where(User.agent_filter == "agents_ok")

    # Seen set
    if listing.id is not None:
        stmt = stmt.where(~User.seen_set.any(listing.id))

    # Distrust set on phone_hash
    if listing.phone_hash:
        stmt = stmt.where(~User.distrust_set.any(listing.phone_hash))

    return list(session.execute(stmt).scalars().all())


def python_filter_pass(user, listing) -> bool:
    """Per-listing Python filters that SQL can't cheaply do.

    Returns True if the (user, listing) pair survives ALL filters.
    """
    # Rooms MUST
    if (user.axis_priority or {}).get("rooms") == "MUST" and user.rooms is not None:
        if listing.rooms != user.rooms:
            return False

    # Area MUST
    if (user.axis_priority or {}).get("area") == "MUST":
        if not _area_match(user.areas or [], listing):
            return False

    # Negative area mask (always applied)
    if user.negative_area_mask and listing.area in user.negative_area_mask:
        return False

    # Structured dealbreakers
    for db_key in (user.dealbreakers or []):
        check = DEALBREAKER_MAP.get(db_key)
        if check is None:
            continue
        if not check(listing):
            return False

    # Dealbreaker keywords
    desc = (listing.description_ru or "").lower()
    for kw in (user.dealbreaker_keywords or []):
        if kw.lower() in desc:
            return False

    # Gender compatibility (only meaningful for shared room / roommate)
    if user.gender_pref and user.gender_pref != GenderConstraint.ANY:
        lc = listing.gender_constraint_listing
        if lc and lc != GenderConstraint.ANY and lc != user.gender_pref:
            return False

    return True


def _area_match(user_areas: list[str], listing) -> bool:
    if not user_areas:
        return True
    listing_area = listing.area
    loc = (listing.location_text or "").lower()
    for a in user_areas:
        if a == listing_area:
            return True
        if a.lower() in loc:
            return True
    return False
