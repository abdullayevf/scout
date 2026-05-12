from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select, text

from apps.shared.enums import MatchState, UserState
from apps.shared.models import Base, Event, Match, User

TG = 600


@pytest.fixture(autouse=True)
def _clean_tables(engine):
    """Truncate all tables after each test so committed rows don't bleed."""
    yield
    with engine.begin() as conn:
        conn.execute(text(
            "TRUNCATE users, listings, matches, events RESTART IDENTITY CASCADE"
        ))


def _user(db_session, tg=TG, state=UserState.ACTIVE):
    from apps.shared.enums import SearchType
    u = User(tg_user_id=tg, state=state, search_type=SearchType.WHOLE_APT_SOLO)
    db_session.add(u)
    db_session.flush()
    return u


def _match(db_session, user_id, state=MatchState.LIKED, **kw):
    m = Match(user_id=user_id, listing_id=60001, score=0.5, reasons=[], state=state, **kw)
    db_session.add(m)
    db_session.flush()
    return m


def _cb(data: str, tg_id: int = TG):
    cb = AsyncMock()
    cb.data = data
    cb.from_user = MagicMock(id=tg_id)
    cb.message = AsyncMock()
    cb.message.text = "chase msg"
    cb.answer = AsyncMock()
    return cb


# --- chase48 yes ---

@pytest.mark.asyncio
async def test_chase_48h_yes_sets_contacted_and_schedules_5d(engine, db_session):
    from apps.bot.handlers.kpi_callbacks import on_chase_48h_yes
    Base.metadata.create_all(engine)
    u = _user(db_session)
    m = _match(db_session, u.id, state=MatchState.LIKED)
    db_session.commit()

    cb = _cb(f"chase48y:{m.id}")
    with patch("apps.bot.handlers.kpi_callbacks.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        await on_chase_48h_yes(cb)

    db_session.refresh(m)
    assert m.state == MatchState.CONTACTED
    assert m.contacted_at is not None
    assert m.chase_5d_due_at is not None
    ev = db_session.execute(select(Event).where(Event.kind == "chase_48h_yes")).scalar_one()
    assert ev.match_id == m.id


# --- chase48 no ---

@pytest.mark.asyncio
async def test_chase_48h_no_writes_event(engine, db_session):
    from apps.bot.handlers.kpi_callbacks import on_chase_48h_no
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=601)
    m = _match(db_session, u.id)
    db_session.commit()

    cb = _cb(f"chase48n:{m.id}", tg_id=601)
    with patch("apps.bot.handlers.kpi_callbacks.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        await on_chase_48h_no(cb)

    ev = db_session.execute(select(Event).where(Event.kind == "chase_48h_no")).scalar_one()
    assert ev.match_id == m.id


# --- chase5 yes ---

@pytest.mark.asyncio
async def test_chase_5d_yes_marks_rented_and_user_success(engine, db_session):
    from apps.bot.handlers.kpi_callbacks import on_chase_5d_yes
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=602)
    m = _match(db_session, u.id, state=MatchState.CONTACTED)
    db_session.commit()

    cb = _cb(f"chase5y:{m.id}", tg_id=602)
    with patch("apps.bot.handlers.kpi_callbacks.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        await on_chase_5d_yes(cb)

    db_session.refresh(m)
    db_session.refresh(u)
    assert m.state == MatchState.RENTED
    assert m.rented_at is not None
    assert u.state == UserState.SUCCESS
    assert u.success_at is not None
    cb.message.answer.assert_called_once()  # congrats message


# --- chase5 no ---

@pytest.mark.asyncio
async def test_chase_5d_no_writes_event(engine, db_session):
    from apps.bot.handlers.kpi_callbacks import on_chase_5d_no
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=603)
    m = _match(db_session, u.id, state=MatchState.CONTACTED)
    db_session.commit()

    cb = _cb(f"chase5n:{m.id}", tg_id=603)
    with patch("apps.bot.handlers.kpi_callbacks.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        await on_chase_5d_no(cb)

    ev = db_session.execute(select(Event).where(Event.kind == "chase_5d_no")).scalar_one()
    assert ev.match_id == m.id


# --- rented:pause ---

@pytest.mark.asyncio
async def test_rented_pause_sets_user_paused(engine, db_session):
    from apps.bot.handlers.kpi_callbacks import on_rented_pause
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=604, state=UserState.SUCCESS)
    db_session.commit()

    cb = _cb("rented:pause", tg_id=604)
    with patch("apps.bot.handlers.kpi_callbacks.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        await on_rented_pause(cb)

    db_session.refresh(u)
    assert u.state == UserState.PAUSED


# --- weekly check-in ---

@pytest.mark.asyncio
async def test_weekly_searching_writes_event(engine, db_session):
    from apps.bot.handlers.kpi_callbacks import on_weekly_searching
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=605)
    db_session.commit()

    cb = _cb("wcheckin:searching", tg_id=605)
    with patch("apps.bot.handlers.kpi_callbacks.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        await on_weekly_searching(cb)

    ev = db_session.execute(
        select(Event).where(Event.kind == "weekly_checkin_searching")
    ).scalar_one()
    assert ev.user_id == u.id


@pytest.mark.asyncio
async def test_weekly_found_marks_success(engine, db_session):
    from apps.bot.handlers.kpi_callbacks import on_weekly_found
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=606)
    db_session.commit()

    cb = _cb("wcheckin:found", tg_id=606)
    with patch("apps.bot.handlers.kpi_callbacks.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        await on_weekly_found(cb)

    db_session.refresh(u)
    assert u.state == UserState.SUCCESS
    assert u.success_at is not None


@pytest.mark.asyncio
async def test_weekly_quit_marks_deleted(engine, db_session):
    from apps.bot.handlers.kpi_callbacks import on_weekly_quit
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=607)
    db_session.commit()

    cb = _cb("wcheckin:quit", tg_id=607)
    with patch("apps.bot.handlers.kpi_callbacks.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        await on_weekly_quit(cb)

    db_session.refresh(u)
    assert u.state == UserState.DELETED
