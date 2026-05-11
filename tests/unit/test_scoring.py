from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from apps.shared.enums import PosterRole
from apps.shared.matching import config as cfg
from apps.shared.matching.score import (
    budget_score,
    commute_score,
    cosine_normalized,
    freshness_score,
    score_listing_for_user,
)


def test_budget_score_in_range():
    assert budget_score(1_500_000, 1_000_000, 2_000_000) == 1.0


def test_budget_score_over_max_decays():
    assert 0 < budget_score(2_500_000, 1_000_000, 2_000_000) < 1.0


def test_budget_score_at_1_5x_max_zero():
    assert budget_score(3_000_000, 1_000_000, 2_000_000) == 0.0


def test_commute_score_in_range():
    assert commute_score(15, 30) == 1.0


def test_commute_score_over_decays():
    assert 0 < commute_score(35, 30) < 1.0


def test_commute_score_at_1_5x_zero():
    assert commute_score(45, 30) == 0.0


def test_freshness_decay_half_at_14_days():
    now = datetime.now(timezone.utc)
    fourteen = now - timedelta(days=14)
    assert abs(freshness_score(fourteen) - 0.5) < 1e-6


def test_freshness_fresh_close_to_one():
    now = datetime.now(timezone.utc) - timedelta(minutes=5)
    assert freshness_score(now) > 0.99


def test_cosine_normalized_bounds():
    assert cosine_normalized(1.0) == 1.0
    assert cosine_normalized(-1.0) == 0.0
    assert cosine_normalized(0.0) == 0.5


@dataclass
class _Listing:
    id: int = 1
    embedding: list = field(default_factory=lambda: [1.0, 0.0, 0.0])
    price_uzs: int = 1_500_000
    posted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc) - timedelta(hours=2))
    area: str = "Yunusabad"
    lat: float | None = 41.3
    lng: float | None = 69.2
    poster_role: str = PosterRole.OWNER
    risk_score: int = 0
    is_furnished: bool | None = True
    has_parking: bool | None = True
    rooms: int | None = 2
    is_first_floor: bool | None = False
    bathroom_type: str | None = "private"
    summary_one_line: str | None = None
    agent_fee_text: str | None = None
    risk_flags: dict | None = None
    description_ru: str | None = ""
    gender_constraint_listing: str | None = "any"
    location_text: str | None = "Yunusabad, ulitsa"


@dataclass
class _User:
    id: int = 1
    preference_embedding: list = field(default_factory=lambda: [1.0, 0.0, 0.0])
    budget_min: int = 1_000_000
    budget_max: int = 2_000_000
    commute_max_minutes: int | None = None
    commute_origin: str | None = None
    commute_origin_lat: float | None = None
    commute_origin_lng: float | None = None
    commute_mode: str | None = None
    axis_priority: dict = field(default_factory=lambda: {
        "budget": "MUST", "area": "NICE", "rooms": "NICE", "commute": "NICE", "furnishing": "NICE",
    })
    rooms: int | None = None
    areas: list = field(default_factory=lambda: ["Yunusabad"])
    is_furnished_pref: bool | None = None


def test_score_returns_in_unit_range_for_basic_match():
    user = _User()
    listing = _Listing()
    score, reasons, components = score_listing_for_user(user, listing)
    assert -0.1 <= score <= 1.0
    assert isinstance(reasons, list)
    assert len(reasons) > 0


def test_score_drops_with_high_risk():
    user = _User()
    fresh = _Listing(risk_score=0)
    risky = _Listing(risk_score=3)
    s_fresh, _, _ = score_listing_for_user(user, fresh)
    s_risky, _, _ = score_listing_for_user(user, risky)
    assert s_fresh > s_risky


def test_score_drops_with_age():
    user = _User()
    fresh = _Listing(posted_at=datetime.now(timezone.utc) - timedelta(minutes=10))
    old = _Listing(posted_at=datetime.now(timezone.utc) - timedelta(days=30))
    s_fresh, _, _ = score_listing_for_user(user, fresh)
    s_old, _, _ = score_listing_for_user(user, old)
    assert s_fresh > s_old


def test_score_commute_used_when_must(monkeypatch):
    user = _User(
        commute_max_minutes=30, commute_mode="car",
        commute_origin="X", commute_origin_lat=41.0, commute_origin_lng=69.0,
        axis_priority={"budget": "MUST", "commute": "MUST"},
    )
    listing = _Listing()
    with patch(
        "apps.shared.matching.score.route_minutes",
        return_value=20,
    ):
        score, reasons, components = score_listing_for_user(user, listing)
    assert components.commute_minutes == 20
    assert any("🚇 20 мин до работы" in r for r in reasons)


def test_score_no_commute_when_origin_missing():
    user = _User(commute_origin=None, commute_origin_lat=None)
    listing = _Listing()
    score, reasons, components = score_listing_for_user(user, listing)
    assert components.commute_minutes is None
    assert not any("🚇" in r for r in reasons)


def test_score_owner_higher_than_agent():
    user = _User()
    owner = _Listing(poster_role=PosterRole.OWNER)
    agent = _Listing(poster_role=PosterRole.AGENT)
    s_owner, _, _ = score_listing_for_user(user, owner)
    s_agent, _, _ = score_listing_for_user(user, agent)
    assert s_owner > s_agent
