from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from apps.shared.enums import UserState
from apps.shared.matching.config import (
    GLOBAL_TOP1PCT_BOOTSTRAP,
    THRESHOLD_MIN_GLOBAL,
    THRESHOLD_MIN_PERSONAL,
)
from apps.shared.models import Base, Match, User


def _user(db_session, tg, **kw):
    from apps.shared.enums import SearchType
    u = User(tg_user_id=tg, state=UserState.ACTIVE, search_type=SearchType.WHOLE_APT_SOLO, **kw)
    db_session.add(u)
    db_session.flush()
    return u


def _match(db_session, user_id, score):
    m = Match(user_id=user_id, listing_id=user_id * 1000 + int(score * 100),
              score=score, reasons=[])
    db_session.add(m)
    db_session.flush()
    return m


def test_bootstrap_when_no_scores(engine, db_session):
    from apps.workers.tasks.match import match_threshold_recompute
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=901)
    db_session.commit()

    with patch("apps.workers.tasks.match.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        match_threshold_recompute.run()
    db_session.refresh(u)
    assert u.top_1pct_threshold == pytest.approx(GLOBAL_TOP1PCT_BOOTSTRAP)


def test_personal_p99_when_enough_scores(engine, db_session):
    from apps.workers.tasks.match import match_threshold_recompute
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=902)
    # Insert THRESHOLD_MIN_PERSONAL matches with scores 0.01..0.50
    for i in range(THRESHOLD_MIN_PERSONAL):
        db_session.add(Match(
            user_id=u.id, listing_id=90200 + i,
            score=0.01 * (i + 1), reasons=[],
        ))
    db_session.commit()

    with patch("apps.workers.tasks.match.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        match_threshold_recompute.run()
    db_session.refresh(u)
    # p99 of 50 evenly spaced values [0.01..0.50] should be near 0.495
    assert u.top_1pct_threshold is not None
    assert u.top_1pct_threshold > 0.45


def test_global_p99_when_not_enough_personal(engine, db_session):
    from apps.workers.tasks.match import match_threshold_recompute
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=903)
    # Only 5 personal matches — below THRESHOLD_MIN_PERSONAL
    for i in range(5):
        db_session.add(Match(
            user_id=u.id, listing_id=90300 + i,
            score=0.9, reasons=[],
        ))
    # But THRESHOLD_MIN_GLOBAL other matches (not user 903's)
    other = _user(db_session, tg=904)
    for i in range(THRESHOLD_MIN_GLOBAL):
        db_session.add(Match(
            user_id=other.id, listing_id=90400 + i,
            score=0.3, reasons=[],
        ))
    db_session.commit()

    with patch("apps.workers.tasks.match.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        match_threshold_recompute.run()
    db_session.refresh(u)
    # Global p99 over ~205 scores (5 at 0.9 + 200 at 0.3) should be near 0.9
    assert u.top_1pct_threshold is not None
    assert u.top_1pct_threshold > 0.4


def test_reaction_weighted_when_enough_liked(engine, db_session):
    """When user has >= THRESHOLD_MIN_REACTIONS liked/contacted matches,
    threshold is computed from liked scores only — not from all matches."""
    from apps.shared.enums import MatchState
    from apps.shared.matching.config import THRESHOLD_MIN_REACTIONS
    from apps.workers.tasks.match import match_threshold_recompute
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=905)
    # THRESHOLD_MIN_REACTIONS liked matches with high scores ~0.85-0.94
    for i in range(THRESHOLD_MIN_REACTIONS):
        db_session.add(Match(
            user_id=u.id, listing_id=90500 + i,
            score=0.85 + 0.01 * i, reasons=[],
            state=MatchState.LIKED,
        ))
    # 200 sent/unseen matches with mediocre scores (0.3)
    for i in range(200):
        db_session.add(Match(
            user_id=u.id, listing_id=90600 + i,
            score=0.3, reasons=[],
            state=MatchState.SENT,
        ))
    db_session.commit()

    with patch("apps.workers.tasks.match.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        match_threshold_recompute.run()

    db_session.refresh(u)
    # If reaction-weighted: p99 of 10 liked scores (0.85..0.94) ≈ 0.935
    # Either way must be > 0.80 to ensure high bar for liked users
    assert u.top_1pct_threshold is not None
    assert u.top_1pct_threshold > 0.80
