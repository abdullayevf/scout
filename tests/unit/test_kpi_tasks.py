from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import text

from apps.shared.enums import MatchState, UserState
from apps.shared.models import Base, Event, Match, User


@pytest.fixture(autouse=True)
def _clean_tables(engine):
    """Truncate all tables after each test so committed rows don't bleed."""
    yield
    with engine.begin() as conn:
        conn.execute(text(
            "TRUNCATE users, listings, matches, events RESTART IDENTITY CASCADE"
        ))


def _user(db_session, tg, state=UserState.ACTIVE, last_active_at=None):
    from apps.shared.enums import SearchType
    u = User(
        tg_user_id=tg, state=state, search_type=SearchType.WHOLE_APT_SOLO,
        last_active_at=last_active_at,
    )
    db_session.add(u)
    db_session.flush()
    return u


def _match(db_session, user_id, listing_id, state, chase_48h_due_at=None,
           chase_48h_done_at=None, chase_5d_due_at=None, chase_5d_done_at=None):
    m = Match(
        user_id=user_id, listing_id=listing_id, score=0.5, reasons=[],
        state=state,
        chase_48h_due_at=chase_48h_due_at,
        chase_48h_done_at=chase_48h_done_at,
        chase_5d_due_at=chase_5d_due_at,
        chase_5d_done_at=chase_5d_done_at,
    )
    db_session.add(m)
    db_session.flush()
    return m


# --- kpi_chase_48h_run ---

def test_kpi_chase_48h_sends_and_marks_done(engine, db_session):
    from apps.workers.tasks.kpi import kpi_chase_48h_run
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=501)
    m = _match(
        db_session, u.id, 5001,
        state=MatchState.LIKED,
        chase_48h_due_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db_session.commit()

    with patch("apps.workers.tasks.kpi.session_scope") as ss, \
         patch("apps.workers.tasks.kpi._bot_send") as mock_send:
        ss.return_value.__enter__.return_value = db_session
        kpi_chase_48h_run.run()

    db_session.refresh(m)
    assert m.chase_48h_done_at is not None
    mock_send.assert_called_once()


def test_kpi_chase_48h_skips_inactive_user(engine, db_session):
    from apps.workers.tasks.kpi import kpi_chase_48h_run
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=502, state=UserState.PAUSED)
    m = _match(
        db_session, u.id, 5002,
        state=MatchState.LIKED,
        chase_48h_due_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db_session.commit()

    with patch("apps.workers.tasks.kpi.session_scope") as ss, \
         patch("apps.workers.tasks.kpi._bot_send") as mock_send:
        ss.return_value.__enter__.return_value = db_session
        kpi_chase_48h_run.run()

    mock_send.assert_not_called()
    db_session.refresh(m)
    assert m.chase_48h_done_at is not None  # still marked done (skip)


def test_kpi_chase_48h_skips_not_yet_due(engine, db_session):
    from apps.workers.tasks.kpi import kpi_chase_48h_run
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=503)
    _match(
        db_session, u.id, 5003,
        state=MatchState.LIKED,
        chase_48h_due_at=datetime.now(UTC) + timedelta(hours=24),
    )
    db_session.commit()

    with patch("apps.workers.tasks.kpi.session_scope") as ss, \
         patch("apps.workers.tasks.kpi._bot_send") as mock_send:
        ss.return_value.__enter__.return_value = db_session
        result = kpi_chase_48h_run.run()

    mock_send.assert_not_called()
    assert result["sent"] == 0


# --- kpi_chase_5d_run ---

def test_kpi_chase_5d_sends_to_contacted_match(engine, db_session):
    from apps.workers.tasks.kpi import kpi_chase_5d_run
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=504)
    m = _match(
        db_session, u.id, 5004,
        state=MatchState.CONTACTED,
        chase_5d_due_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db_session.commit()

    with patch("apps.workers.tasks.kpi.session_scope") as ss, \
         patch("apps.workers.tasks.kpi._bot_send") as mock_send:
        ss.return_value.__enter__.return_value = db_session
        result = kpi_chase_5d_run.run()

    db_session.refresh(m)
    assert m.chase_5d_done_at is not None
    mock_send.assert_called_once()
    assert result["sent"] == 1


# --- kpi_weekly_checkin_send ---

def test_kpi_weekly_checkin_sends_to_active_users(engine, db_session):
    from apps.workers.tasks.kpi import kpi_weekly_checkin_send
    Base.metadata.create_all(engine)
    _user(db_session, tg=505)
    _user(db_session, tg=506)
    _user(db_session, tg=507, state=UserState.PAUSED)
    db_session.commit()

    with patch("apps.workers.tasks.kpi.session_scope") as ss, \
         patch("apps.workers.tasks.kpi._bot_send") as mock_send:
        ss.return_value.__enter__.return_value = db_session
        result = kpi_weekly_checkin_send.run()

    assert result["sent"] == 2
    assert mock_send.call_count == 2


# --- kpi_maintenance_purge_inactive ---

def test_kpi_purge_inactive_deletes_old_users(engine, db_session):
    from apps.workers.tasks.kpi import kpi_maintenance_purge_inactive
    Base.metadata.create_all(engine)
    stale = _user(db_session, tg=508,
                  last_active_at=datetime.now(UTC) - timedelta(days=100))
    fresh = _user(db_session, tg=509,
                  last_active_at=datetime.now(UTC) - timedelta(days=10))
    db_session.commit()

    with patch("apps.workers.tasks.kpi.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        result = kpi_maintenance_purge_inactive.run()

    db_session.refresh(stale)
    db_session.refresh(fresh)
    assert stale.state == UserState.DELETED
    assert fresh.state == UserState.ACTIVE
    assert result["deleted"] == 1
