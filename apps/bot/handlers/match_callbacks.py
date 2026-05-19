"""Match action button handlers — state transitions + ML feedback (Plan 4)."""

import logging
from datetime import UTC, datetime, timedelta

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select

from apps.bot.keyboards import dislike_reasons_kb
from apps.shared.db import session_scope
from apps.shared.enums import MatchState
from apps.shared.feedback import (
    apply_contact, apply_dislike_area, apply_dislike_expensive,
    apply_dislike_fishy, apply_dislike_generic, apply_dislike_seen, apply_like,
)
from apps.shared.models import Event, Listing, Match, User

log = logging.getLogger(__name__)
router = Router(name="match_callbacks")


def _owns_match(
    s, match_id: int, tg_user_id: int
) -> tuple[Match, User] | tuple[None, None]:
    """Return (match, user) if the Telegram user owns the match, else (None, None)."""
    m = s.get(Match, match_id)
    if m is None:
        return None, None
    u = s.execute(
        select(User).where(User.tg_user_id == tg_user_id)
    ).scalar_one_or_none()
    if u is None or u.id != m.user_id:
        return None, None
    return m, u


@router.callback_query(F.data.startswith("like:"))
async def on_like(cb: CallbackQuery) -> None:
    match_id = int(cb.data.split(":", 1)[1])
    with session_scope() as s:
        m, u = _owns_match(s, match_id, cb.from_user.id)
        if m is None:
            await cb.answer()
            return
        if m.state not in (MatchState.PENDING, MatchState.SENT):
            await cb.answer()
            return
        listing = s.get(Listing, m.listing_id)
        if listing:
            apply_like(u, listing)
        m.state = MatchState.LIKED
        m.liked_at = datetime.now(UTC)
        m.chase_48h_due_at = datetime.now(UTC) + timedelta(hours=48)
        s.add(Event(kind="match_btn_like", user_id=cb.from_user.id, match_id=match_id))
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.edit_text((cb.message.text or "") + "\n\n✅ Запомнил.")
    await cb.answer()


@router.callback_query(F.data.startswith("dislike:"))
async def on_dislike_open(cb: CallbackQuery) -> None:
    match_id = int(cb.data.split(":", 1)[1])
    with session_scope() as s:
        m, _ = _owns_match(s, match_id, cb.from_user.id)
        if m is None:
            await cb.answer()
            return
        s.add(Event(kind="match_btn_dislike_open", user_id=cb.from_user.id, match_id=match_id))
    await cb.message.edit_reply_markup(reply_markup=dislike_reasons_kb(match_id))
    await cb.answer()


_DISLIKE_HANDLERS = {
    "expensive": apply_dislike_expensive,
    "area":      apply_dislike_area,
    "fishy":     apply_dislike_fishy,
}


@router.callback_query(F.data.startswith("dislike_reason:"))
async def on_dislike_reason(cb: CallbackQuery) -> None:
    _, reason, mid = cb.data.split(":")
    match_id = int(mid)
    with session_scope() as s:
        m, u = _owns_match(s, match_id, cb.from_user.id)
        if m is None:
            await cb.answer()
            return
        if m.state not in (MatchState.PENDING, MatchState.SENT):
            await cb.answer()
            return
        listing = s.get(Listing, m.listing_id)
        if listing:
            if reason == "seen":
                apply_dislike_seen(u, listing.id)
            elif reason in _DISLIKE_HANDLERS:
                _DISLIKE_HANDLERS[reason](u, listing)
            else:
                apply_dislike_generic(u, listing)
        m.state = MatchState.DISLIKED
        m.disliked_at = datetime.now(UTC)
        m.dislike_reason = reason
        s.add(Event(
            kind="match_btn_dislike_reason",
            user_id=cb.from_user.id, match_id=match_id,
            payload={"reason": reason},
        ))
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.edit_text((cb.message.text or "") + "\n\n👌")
    await cb.answer()


@router.callback_query(F.data.startswith("contact:"))
async def on_contact(cb: CallbackQuery) -> None:
    match_id = int(cb.data.split(":", 1)[1])
    with session_scope() as s:
        m, u = _owns_match(s, match_id, cb.from_user.id)
        if m is None:
            await cb.answer()
            return
        if m.state in (MatchState.DISLIKED, MatchState.CONTACTED, MatchState.RENTED, MatchState.DEAD):
            await cb.answer()
            return
        listing = s.get(Listing, m.listing_id)
        phone = listing.contact_phone_raw if listing else None
        if listing:
            apply_contact(u, listing)
        m.state = MatchState.CONTACTED
        m.contacted_at = datetime.now(UTC)
        m.chase_48h_due_at = datetime.now(UTC) + timedelta(hours=48)
        s.add(Event(kind="match_btn_contact", user_id=cb.from_user.id, match_id=match_id))
    if phone:
        new_text = (cb.message.text or "") + f"\n\n📞 {phone}"
        await cb.message.edit_text(new_text, reply_markup=None)
    else:
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.answer("Номер не найден — открой объявление на OLX", show_alert=True)
        return
    await cb.answer()
