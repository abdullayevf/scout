from dataclasses import dataclass

import pytest

from apps.shared.enums import MatchState, UserState
from apps.shared.matching.coldstart import is_cold_start, stratified_pick
from apps.shared.matching.config import COLD_START_REACTIONS
from apps.shared.models import Base, Match, User


@dataclass
class _Pick:
    """Stand-in for a Match row in stratifier tests."""

    id: int
    score: float
    price_uzs: int
    area: str
    is_furnished: bool | None
    listing_id: int = 0

    def __post_init__(self):
        if self.listing_id == 0:
            self.listing_id = self.id


def test_is_cold_start_true_when_zero_reactions(engine, db_session):
    Base.metadata.create_all(engine)
    u = User(tg_user_id=100, state=UserState.ACTIVE)
    db_session.add(u)
    db_session.flush()
    assert is_cold_start(db_session, u) is True


def test_is_cold_start_false_when_threshold_met(engine, db_session):
    Base.metadata.create_all(engine)
    u = User(tg_user_id=101, state=UserState.ACTIVE)
    db_session.add(u)
    db_session.flush()
    for i in range(COLD_START_REACTIONS):
        db_session.add(Match(
            user_id=u.id, listing_id=1000 + i,
            score=0.5, reasons=[], state=MatchState.LIKED,
        ))
    db_session.flush()
    assert is_cold_start(db_session, u) is False


def test_is_cold_start_counts_disliked_and_contacted(engine, db_session):
    Base.metadata.create_all(engine)
    u = User(tg_user_id=102, state=UserState.ACTIVE)
    db_session.add(u)
    db_session.flush()
    states = [MatchState.LIKED] * 4 + [MatchState.DISLIKED] * 4 + [MatchState.CONTACTED] * 2
    for i, st in enumerate(states):
        db_session.add(Match(
            user_id=u.id, listing_id=2000 + i,
            score=0.5, reasons=[], state=st,
        ))
    db_session.flush()
    assert is_cold_start(db_session, u) is False


def test_is_cold_start_ignores_pending_and_sent(engine, db_session):
    Base.metadata.create_all(engine)
    u = User(tg_user_id=103, state=UserState.ACTIVE)
    db_session.add(u)
    db_session.flush()
    for i in range(20):
        db_session.add(Match(
            user_id=u.id, listing_id=3000 + i,
            score=0.5, reasons=[], state=MatchState.SENT,
        ))
    db_session.flush()
    assert is_cold_start(db_session, u) is True


@dataclass
class _User:
    areas: list[str]


def _pool() -> list[_Pick]:
    return [
        _Pick(id=1,  score=0.9, price_uzs=1_000_000, area="A", is_furnished=True),
        _Pick(id=2,  score=0.88, price_uzs=1_100_000, area="A", is_furnished=True),
        _Pick(id=3,  score=0.86, price_uzs=1_200_000, area="A", is_furnished=True),
        _Pick(id=4,  score=0.85, price_uzs=1_300_000, area="B", is_furnished=False),
        _Pick(id=5,  score=0.80, price_uzs=1_400_000, area="B", is_furnished=False),
        _Pick(id=6,  score=0.78, price_uzs=1_500_000, area="C", is_furnished=False),
        _Pick(id=7,  score=0.70, price_uzs=1_700_000, area="C", is_furnished=True),
        _Pick(id=8,  score=0.60, price_uzs=2_000_000, area="D", is_furnished=False),
        _Pick(id=9,  score=0.55, price_uzs=2_200_000, area="D", is_furnished=True),
        _Pick(id=10, score=0.40, price_uzs=2_500_000, area="A", is_furnished=False),
    ]


def test_stratified_pick_returns_k_or_pool_size():
    user = _User(areas=["A", "B", "C", "D"])
    picks = stratified_pick(_pool(), user, k=8)
    assert len(picks) == 8


def test_stratified_pick_small_pool_no_pad():
    user = _User(areas=["A", "B"])
    pool = _pool()[:3]
    picks = stratified_pick(pool, user, k=8)
    assert len(picks) == 3


def test_stratified_pick_covers_at_least_three_areas_when_possible():
    user = _User(areas=["A", "B", "C", "D"])
    picks = stratified_pick(_pool(), user, k=8)
    distinct_areas = {p.area for p in picks}
    assert len(distinct_areas) >= 3


def test_stratified_pick_mixes_furnishing_when_possible():
    user = _User(areas=["A", "B", "C", "D"])
    picks = stratified_pick(_pool(), user, k=8)
    furn = {p.is_furnished for p in picks}
    assert furn == {True, False}
