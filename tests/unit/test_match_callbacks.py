from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sqlalchemy import select
from apps.bot.handlers.match_callbacks import on_contact, on_dislike_open, on_dislike_reason, on_like
from apps.shared.enums import ListingState, MatchState, SearchType, UserState
from apps.shared.models import Base, Event, Listing, Match, User

TG_USER_ID = 123


def _make_cb(data: str, user_id: int = TG_USER_ID):
    cb = AsyncMock()
    cb.data = data
    cb.from_user = MagicMock(id=user_id, username="u")
    cb.message = AsyncMock()
    cb.message.text = "🏠 2-комн., Юнусабад\n💰 1 400 000 UZS"
    cb.answer = AsyncMock()
    return cb


def _make_user(db_session, tg_user_id: int = TG_USER_ID) -> User:
    u = User(tg_user_id=tg_user_id, state=UserState.ACTIVE,
             search_type=SearchType.WHOLE_APT_SOLO)
    db_session.add(u)
    db_session.flush()
    return u


@pytest.mark.asyncio
async def test_on_like_writes_event_and_edits_message(engine, db_session):
    Base.metadata.create_all(engine)
    u = _make_user(db_session)
    match = Match(user_id=u.id, listing_id=9999, score=0.5, reasons=[])
    db_session.add(match)
    db_session.flush()
    cb = _make_cb(f"like:{match.id}")
    with patch("apps.bot.handlers.match_callbacks.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        await on_like(cb)
    db_session.flush()
    ev = db_session.execute(
        select(Event).where(Event.kind == "match_btn_like")
    ).scalar_one()
    assert ev.match_id == match.id
    assert ev.user_id == TG_USER_ID
    cb.message.edit_reply_markup.assert_called_once()
    cb.message.edit_text.assert_called_once()
    cb.answer.assert_called_once()


@pytest.mark.asyncio
async def test_on_dislike_open_writes_event_and_swaps_kb(engine, db_session):
    Base.metadata.create_all(engine)
    u = _make_user(db_session)
    match = Match(user_id=u.id, listing_id=9998, score=0.5, reasons=[])
    db_session.add(match)
    db_session.flush()
    cb = _make_cb(f"dislike:{match.id}")
    with patch("apps.bot.handlers.match_callbacks.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        await on_dislike_open(cb)
    db_session.flush()
    ev = db_session.execute(
        select(Event).where(Event.kind == "match_btn_dislike_open")
    ).scalar_one()
    assert ev.match_id == match.id
    cb.message.edit_reply_markup.assert_called_once()
    cb.message.edit_text.assert_not_called()


@pytest.mark.asyncio
async def test_on_dislike_reason_records_reason(engine, db_session):
    Base.metadata.create_all(engine)
    u = _make_user(db_session)
    match = Match(user_id=u.id, listing_id=9997, score=0.5, reasons=[])
    db_session.add(match)
    db_session.flush()
    cb = _make_cb(f"dislike_reason:fishy:{match.id}")
    with patch("apps.bot.handlers.match_callbacks.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        await on_dislike_reason(cb)
    db_session.flush()
    ev = db_session.execute(
        select(Event).where(Event.kind == "match_btn_dislike_reason")
    ).scalar_one()
    assert ev.payload["reason"] == "fishy"
    assert ev.match_id == match.id


@pytest.mark.asyncio
async def test_on_contact_reveals_phone(engine, db_session):
    Base.metadata.create_all(engine)
    u = _make_user(db_session)
    listing = Listing(
        source_url="https://www.olx.uz/x", source_listing_id="x",
        source_category="long_term_apt",
        title="t", description_raw="", state=ListingState.ACTIVE,
        contact_phone_raw="+998901112233",
        image_urls=[], image_phashes=[],
    )
    db_session.add(listing)
    db_session.flush()
    match = Match(user_id=u.id, listing_id=listing.id, score=0.5, reasons=[])
    db_session.add(match)
    db_session.flush()
    cb = _make_cb(f"contact:{match.id}")
    cb.message.answer = AsyncMock()
    with patch("apps.bot.handlers.match_callbacks.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        await on_contact(cb)
    cb.message.answer.assert_called_once()
    sent = cb.message.answer.call_args[0][0]
    assert "+998901112233" in sent
    assert listing.source_url in sent
    cb.message.edit_reply_markup.assert_called_once()


@pytest.mark.asyncio
async def test_on_like_rejects_foreign_match(engine, db_session):
    """A user must not be able to interact with another user's match."""
    Base.metadata.create_all(engine)
    owner = _make_user(db_session, tg_user_id=200)
    match = Match(user_id=owner.id, listing_id=8888, score=0.5, reasons=[])
    db_session.add(match)
    db_session.flush()
    # Attacker has tg_user_id=201
    attacker_cb = _make_cb(f"like:{match.id}", user_id=201)
    with patch("apps.bot.handlers.match_callbacks.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        await on_like(attacker_cb)
    db_session.flush()
    # No event should have been written
    count = db_session.execute(
        select(Event).where(Event.kind == "match_btn_like")
    ).scalars().all()
    assert len(count) == 0
    # message should NOT have been edited
    attacker_cb.message.edit_text.assert_not_called()
    attacker_cb.answer.assert_called_once()


@pytest.mark.asyncio
async def test_on_contact_rejects_foreign_match(engine, db_session):
    """An attacker must not receive another user's phone number."""
    Base.metadata.create_all(engine)
    owner = _make_user(db_session, tg_user_id=300)
    listing = Listing(
        source_url="https://www.olx.uz/secret", source_listing_id="secret",
        source_category="long_term_apt",
        title="t", description_raw="", state=ListingState.ACTIVE,
        contact_phone_raw="+998999999999",
        image_urls=[], image_phashes=[],
    )
    db_session.add(listing)
    db_session.flush()
    match = Match(user_id=owner.id, listing_id=listing.id, score=0.5, reasons=[])
    db_session.add(match)
    db_session.flush()
    attacker_cb = _make_cb(f"contact:{match.id}", user_id=301)
    attacker_cb.message.answer = AsyncMock()
    with patch("apps.bot.handlers.match_callbacks.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        await on_contact(attacker_cb)
    attacker_cb.message.answer.assert_not_called()
    attacker_cb.answer.assert_called_once()
