from dataclasses import dataclass, field

import pytest

from apps.shared.enums import (
    GenderConstraint,
    ListingState,
    MatchState,
    PosterRole,
    SearchType,
    UserState,
)
from apps.shared.matching.filters import (
    SEARCH_TYPE_COMPAT,
    python_filter_pass,
    sql_filter_candidates,
)
from apps.shared.models import Base, Listing, User


@dataclass
class _Listing:
    rooms: int | None = 2
    area: str | None = "Yunusabad"
    location_text: str | None = "Юнусабад, ул. Лабзак"
    is_first_floor: bool | None = False
    bathroom_type: str | None = "private"
    has_parking: bool | None = True
    description_ru: str | None = "Хорошая квартира"
    gender_constraint_listing: str | None = GenderConstraint.ANY


def _user(**kw):
    @dataclass
    class U:
        id: int = 1
        rooms: int | None = None
        areas: list = field(default_factory=lambda: ["Yunusabad"])
        commute_max_minutes: int | None = None
        commute_origin: str | None = None
        commute_mode: str | None = None
        commute_origin_lat: float | None = None
        commute_origin_lng: float | None = None
        dealbreakers: list = field(default_factory=list)
        dealbreaker_keywords: list = field(default_factory=list)
        negative_area_mask: list = field(default_factory=list)
        gender_pref: str | None = None
        axis_priority: dict = field(default_factory=lambda: {})
    return U(**kw)


def test_search_type_compat_solo_accepts_whole_apt():
    assert "whole_apt_solo" in SEARCH_TYPE_COMPAT[SearchType.WHOLE_APT_SOLO]
    assert "whole_apt_family" in SEARCH_TYPE_COMPAT[SearchType.WHOLE_APT_SOLO]


def test_search_type_compat_shared_room_only_shared():
    compat = SEARCH_TYPE_COMPAT[SearchType.SHARED_ROOM]
    assert "shared_room" in compat
    assert "whole_apt_family" not in compat


def test_python_filter_rooms_mismatch_drops():
    user = _user(rooms=3, axis_priority={"rooms": "MUST"})
    listing = _Listing(rooms=2)
    assert python_filter_pass(user, listing) is False


def test_python_filter_rooms_any_passes():
    user = _user(rooms=None, axis_priority={"rooms": "MUST"})
    listing = _Listing(rooms=2)
    assert python_filter_pass(user, listing) is True


def test_python_filter_area_must_passes_on_tuman():
    user = _user(areas=["Yunusabad"], axis_priority={"area": "MUST"})
    listing = _Listing(area="Yunusabad", location_text="X")
    assert python_filter_pass(user, listing) is True


def test_python_filter_area_must_drops_when_tuman_mismatch_and_no_substring():
    user = _user(areas=["Chilanzar"], axis_priority={"area": "MUST"})
    listing = _Listing(area="Yunusabad", location_text="Yunusabad street")
    assert python_filter_pass(user, listing) is False


def test_python_filter_area_must_passes_via_substring():
    user = _user(areas=["Лабзак"], axis_priority={"area": "MUST"})
    listing = _Listing(area="Yunusabad", location_text="ул. Лабзак 10")
    assert python_filter_pass(user, listing) is True


def test_python_filter_dealbreaker_first_floor_drops():
    user = _user(dealbreakers=["no_first_floor"])
    listing = _Listing(is_first_floor=True)
    assert python_filter_pass(user, listing) is False


def test_python_filter_dealbreaker_shared_bathroom_drops():
    user = _user(dealbreakers=["no_shared_bathroom"])
    listing = _Listing(bathroom_type="shared")
    assert python_filter_pass(user, listing) is False


def test_python_filter_dealbreaker_parking_required():
    user = _user(dealbreakers=["must_have_parking"])
    listing = _Listing(has_parking=False)
    assert python_filter_pass(user, listing) is False


def test_python_filter_keyword_drops():
    user = _user(dealbreaker_keywords=["евроремонт"])
    listing = _Listing(description_ru="свежий евроремонт")
    assert python_filter_pass(user, listing) is False


def test_python_filter_negative_area_mask_drops():
    user = _user(negative_area_mask=["Yunusabad"])
    listing = _Listing(area="Yunusabad")
    assert python_filter_pass(user, listing) is False


def test_python_filter_gender_mismatch_drops():
    user = _user(gender_pref="female")
    listing = _Listing(gender_constraint_listing="male")
    assert python_filter_pass(user, listing) is False


def test_python_filter_gender_any_passes():
    user = _user(gender_pref="female")
    listing = _Listing(gender_constraint_listing=GenderConstraint.ANY)
    assert python_filter_pass(user, listing) is True


# SQL filter (integration test against testcontainers Postgres)
def test_sql_filter_drops_paused_user(engine, db_session):
    Base.metadata.create_all(engine)
    db_session.add(User(
        tg_user_id=501, state=UserState.PAUSED,
        search_type=SearchType.WHOLE_APT_SOLO,
        budget_min=1_000_000, budget_max=2_000_000,
        axis_priority={"budget": "MUST"},
        agent_filter="agents_ok",
    ))
    db_session.add(User(
        tg_user_id=502, state=UserState.ACTIVE,
        search_type=SearchType.WHOLE_APT_SOLO,
        budget_min=1_000_000, budget_max=2_000_000,
        axis_priority={"budget": "MUST"},
        agent_filter="agents_ok",
    ))
    db_session.flush()

    listing = Listing(
        source_url="https://www.olx.uz/x1", source_listing_id="x1",
        source_category="long_term_apt",
        title="t", description_raw="", state=ListingState.ACTIVE,
        price_uzs=1_500_000, search_type_listing=SearchType.WHOLE_APT_SOLO,
        poster_role=PosterRole.OWNER, phone_hash="p1",
    )
    db_session.add(listing)
    db_session.flush()

    users = sql_filter_candidates(db_session, listing)
    assert len(users) == 1
    assert users[0].tg_user_id == 502


def test_sql_filter_budget_must_drops_out_of_range(engine, db_session):
    Base.metadata.create_all(engine)
    u_strict = User(
        tg_user_id=601, state=UserState.ACTIVE,
        search_type=SearchType.WHOLE_APT_SOLO,
        budget_min=1_000_000, budget_max=2_000_000,
        axis_priority={"budget": "MUST"},
        agent_filter="agents_ok",
    )
    u_nice = User(
        tg_user_id=602, state=UserState.ACTIVE,
        search_type=SearchType.WHOLE_APT_SOLO,
        budget_min=1_000_000, budget_max=2_000_000,
        axis_priority={"budget": "NICE"},
        agent_filter="agents_ok",
    )
    db_session.add_all([u_strict, u_nice])
    db_session.flush()

    listing = Listing(
        source_url="https://www.olx.uz/x2", source_listing_id="x2",
        source_category="long_term_apt",
        title="t", description_raw="", state=ListingState.ACTIVE,
        price_uzs=3_000_000, search_type_listing=SearchType.WHOLE_APT_SOLO,
        poster_role=PosterRole.OWNER, phone_hash="p2",
    )
    db_session.add(listing)
    db_session.flush()

    users = sql_filter_candidates(db_session, listing)
    tg_ids = {u.tg_user_id for u in users}
    assert 601 not in tg_ids
    assert 602 in tg_ids
