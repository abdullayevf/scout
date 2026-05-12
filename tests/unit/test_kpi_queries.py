from datetime import UTC, datetime, timedelta

import pytest

from apps.shared.enums import MatchState, UserState
from apps.shared.models import Base, Match, User


def _user(db_session, tg, state=UserState.ACTIVE, success_at=None, created_at=None):
    from apps.shared.enums import SearchType
    kw = {}
    if created_at:
        kw["created_at"] = created_at
    u = User(tg_user_id=tg, state=state, search_type=SearchType.WHOLE_APT_SOLO,
             success_at=success_at, **kw)
    db_session.add(u)
    db_session.flush()
    return u


def _match(db_session, user_id, state, listing_id):
    m = Match(user_id=user_id, listing_id=listing_id, score=0.5, reasons=[], state=state)
    db_session.add(m)
    db_session.flush()
    return m


@pytest.fixture(autouse=True)
def clean_tables(engine, db_session):
    """Drop and recreate all tables before each test to ensure isolation."""
    db_session.close()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


def test_like_rate_correct(engine, db_session):
    from apps.shared.kpi import like_rate
    u = _user(db_session, tg=701)
    _match(db_session, u.id, MatchState.LIKED, 7001)
    _match(db_session, u.id, MatchState.SENT, 7002)
    _match(db_session, u.id, MatchState.DISLIKED, 7003)
    db_session.commit()
    # 1 liked out of 3 reacted = 0.333...
    rate = like_rate(db_session, days=365)
    assert abs(rate - 1 / 3) < 0.01


def test_contact_rate_correct(engine, db_session):
    from apps.shared.kpi import contact_rate
    u = _user(db_session, tg=702)
    _match(db_session, u.id, MatchState.CONTACTED, 7004)
    _match(db_session, u.id, MatchState.LIKED, 7005)
    _match(db_session, u.id, MatchState.DISLIKED, 7006)
    db_session.commit()
    rate = contact_rate(db_session, days=365)
    assert abs(rate - 1 / 3) < 0.01


def test_days_to_success_median(engine, db_session):
    from apps.shared.kpi import days_to_success
    now = datetime.now(UTC)
    _user(db_session, tg=703, success_at=now - timedelta(days=5))
    _user(db_session, tg=704, success_at=now - timedelta(days=10))
    _user(db_session, tg=705, success_at=now - timedelta(days=20))
    db_session.commit()
    d = days_to_success(db_session)
    # created_at defaults to server now(), success_at is in the past,
    # so |success_at - created_at| ≈ 5, 10, 20 days; median ≈ 10
    assert d is not None
    assert 4 < d < 21  # loose bound


def test_days_to_success_none_when_no_success(engine, db_session):
    from apps.shared.kpi import days_to_success
    _user(db_session, tg=706)
    db_session.commit()
    assert days_to_success(db_session) is None


def test_mute_rate_correct(engine, db_session):
    from apps.shared.kpi import mute_rate
    reacted = _user(db_session, tg=707)
    muted = _user(db_session, tg=708)
    _match(db_session, reacted.id, MatchState.LIKED, 7009)
    # muted user has only SENT matches
    _match(db_session, muted.id, MatchState.SENT, 7010)
    db_session.commit()
    rate = mute_rate(db_session, days=365)
    assert abs(rate - 0.5) < 0.01  # 1 of 2 active users muted


def test_mute_rate_zero_when_no_active_users(engine, db_session):
    from apps.shared.kpi import mute_rate
    Base.metadata.create_all(engine)
    db_session.commit()
    assert mute_rate(db_session, days=365) == 0.0
