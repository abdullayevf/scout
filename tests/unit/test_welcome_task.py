from datetime import UTC, datetime, timedelta
from collections import namedtuple
from unittest.mock import patch, call

import pytest
from sqlalchemy import text

from apps.shared.enums import (
    DeliveredVia, GenderConstraint, ListingState, MatchState,
    PosterRole, SearchType, UserState,
)
from apps.shared.models import Base, Event, Listing, Match, User


@pytest.fixture(autouse=True)
def _clean(engine):
    yield
    with engine.begin() as conn:
        conn.execute(text(
            "TRUNCATE users, listings, matches, events RESTART IDENTITY CASCADE"
        ))


def _user(db_session, tg, **kw):
    defaults = dict(
        state=UserState.ACTIVE,
        search_type=SearchType.WHOLE_APT_SOLO,
        budget_min=1_000_000, budget_max=3_000_000,
        areas=["Yunusabad"],
        axis_priority={"budget": "NICE"},
        agent_filter="agents_ok",
        gender_pref=GenderConstraint.ANY,
        preference_embedding=[0.1] * 3072,
    )
    defaults.update(kw)
    u = User(tg_user_id=tg, **defaults)
    db_session.add(u)
    db_session.flush()
    return u


def _listing(db_session, days_old=1, **kw):
    sid = kw.pop("sid", "x")
    defaults = dict(
        source="olx",
        source_listing_id=sid,
        source_category="long_term_apt",
        source_url=f"https://www.olx.uz/{sid}",
        title="t", description_raw="", description_ru="тихая квартира",
        state=ListingState.ACTIVE,
        price_uzs=1_500_000, rooms=2, area="Yunusabad",
        search_type_listing=SearchType.WHOLE_APT_SOLO,
        gender_constraint_listing=GenderConstraint.ANY,
        poster_role=PosterRole.OWNER,
        phone_hash="ph",
        posted_at=datetime.now(UTC) - timedelta(days=days_old),
        embedding=[0.1] * 3072,
        risk_score=0, suppressed=False,
        is_furnished=True, has_parking=False, is_first_floor=False,
        bathroom_type="private",
        image_urls=[], image_phashes=[],
    )
    defaults.update(kw)
    l = Listing(**defaults)
    db_session.add(l)
    db_session.flush()
    return l


def test_welcome_skips_inactive_user(engine, db_session):
    from apps.workers.tasks.match import match_welcome_for_user
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=901, state=UserState.PAUSED)
    db_session.commit()

    with patch("apps.workers.tasks.match.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        result = match_welcome_for_user.run(u.id)

    assert result == {"ok": False, "reason": "user inactive"}
    assert db_session.query(Match).count() == 0


def test_welcome_skips_listings_older_than_7_days(engine, db_session):
    from apps.workers.tasks.match import match_welcome_for_user
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=902)
    _listing(db_session, sid="old", days_old=8)
    db_session.commit()

    with patch("apps.workers.tasks.match.session_scope") as ss, \
         patch("apps.workers.tasks.match.send_match_message") as sm, \
         patch("apps.workers.tasks.match.send_plain_text") as st:
        ss.return_value.__enter__.return_value = db_session
        result = match_welcome_for_user.run(u.id)

    assert result == {"ok": True, "matches": 0}
    sm.assert_not_called()
    st.assert_not_called()


def test_welcome_skips_suppressed_listing(engine, db_session):
    from apps.workers.tasks.match import match_welcome_for_user
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=903)
    _listing(db_session, sid="sup", suppressed=True)
    db_session.commit()

    with patch("apps.workers.tasks.match.session_scope") as ss, \
         patch("apps.workers.tasks.match.send_match_message") as sm, \
         patch("apps.workers.tasks.match.send_plain_text"):
        ss.return_value.__enter__.return_value = db_session
        result = match_welcome_for_user.run(u.id)

    assert result == {"ok": True, "matches": 0}
    sm.assert_not_called()


def test_welcome_sends_top_5_and_closing(engine, db_session):
    from apps.workers.tasks.match import match_welcome_for_user
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=904)
    for i in range(8):
        _listing(db_session, sid=f"l{i}", days_old=1 + i % 3,
                 embedding=[0.1 + i * 0.01] * 3072)
    db_session.commit()

    with patch("apps.workers.tasks.match.session_scope") as ss, \
         patch("apps.workers.tasks.match.send_match_message") as sm, \
         patch("apps.workers.tasks.match.send_plain_text") as st:
        ss.return_value.__enter__.return_value = db_session
        result = match_welcome_for_user.run(u.id)

    assert result["ok"] is True
    assert result["matches"] == 5
    assert sm.call_count == 5
    st.assert_called_once()
    closing_text = st.call_args[0][1]
    assert "5" in closing_text
    assert "09:00" in closing_text


def test_welcome_marks_delivered_via_welcome(engine, db_session):
    from apps.workers.tasks.match import match_welcome_for_user
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=905)
    _listing(db_session, sid="w1")
    db_session.commit()

    with patch("apps.workers.tasks.match.session_scope") as ss, \
         patch("apps.workers.tasks.match.send_match_message"), \
         patch("apps.workers.tasks.match.send_plain_text"):
        ss.return_value.__enter__.return_value = db_session
        match_welcome_for_user.run(u.id)

    matches = db_session.query(Match).filter_by(user_id=u.id).all()
    sent = [m for m in matches if m.state == MatchState.SENT]
    assert all(m.delivered_via == DeliveredVia.WELCOME for m in sent)


def test_welcome_logs_events(engine, db_session):
    from apps.workers.tasks.match import match_welcome_for_user
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=906)
    _listing(db_session, sid="e1")
    db_session.commit()

    with patch("apps.workers.tasks.match.session_scope") as ss, \
         patch("apps.workers.tasks.match.send_match_message"), \
         patch("apps.workers.tasks.match.send_plain_text"):
        ss.return_value.__enter__.return_value = db_session
        result = match_welcome_for_user.run(u.id)

    events = db_session.query(Event).filter_by(kind="match_sent_welcome").all()
    assert len(events) == result["matches"]


def test_welcome_idempotent_skips_existing_matches(engine, db_session):
    from apps.workers.tasks.match import match_welcome_for_user
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=907)
    l = _listing(db_session, sid="dup")
    db_session.add(Match(user_id=u.id, listing_id=l.id, score=0.5, reasons=[], state=MatchState.SENT))
    db_session.commit()

    with patch("apps.workers.tasks.match.session_scope") as ss, \
         patch("apps.workers.tasks.match.send_match_message") as sm, \
         patch("apps.workers.tasks.match.send_plain_text"):
        ss.return_value.__enter__.return_value = db_session
        result = match_welcome_for_user.run(u.id)

    assert result == {"ok": True, "matches": 0}
    sm.assert_not_called()
    assert db_session.query(Match).count() == 1  # no new rows
