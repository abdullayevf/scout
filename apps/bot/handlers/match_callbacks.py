"""Stub callback handlers for match action buttons.

Plan 3 does NOT transition matches.state — it only writes events. Plan 4
will own the ML feedback path. The one exception is the contact button:
it reveals the listing's phone number.
"""

import logging
from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select
from apps.bot.keyboards import dislike_reasons_kb
from apps.shared.db import session_scope
from apps.shared.models import Event, Listing, Match, User

log = logging.getLogger(__name__)
router = Router(name="match_callbacks")


def _owns_match(s, match_id: int, tg_user_id: int) -> Match | None:
    """Return the Match if the Telegram user owns it, else None."""
    m = s.get(Match, match_id)
    if m is None:
        return None
    u = s.execute(
        select(User).where(User.tg_user_id == tg_user_id)
    ).scalar_one_or_none()
    if u is None or u.id != m.user_id:
        return None
    return m


@router.callback_query(F.data.startswith("like:"))
async def on_like(cb: CallbackQuery) -> None:
    match_id = int(cb.data.split(":", 1)[1])
    with session_scope() as s:
        if _owns_match(s, match_id, cb.from_user.id) is None:
            await cb.answer()
            return
        s.add(Event(kind="match_btn_like", user_id=cb.from_user.id, match_id=match_id))
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.edit_text((cb.message.text or "") + "\n\n✅ Запомнил.")
    await cb.answer()


@router.callback_query(F.data.startswith("dislike:"))
async def on_dislike_open(cb: CallbackQuery) -> None:
    match_id = int(cb.data.split(":", 1)[1])
    with session_scope() as s:
        if _owns_match(s, match_id, cb.from_user.id) is None:
            await cb.answer()
            return
        s.add(Event(kind="match_btn_dislike_open", user_id=cb.from_user.id, match_id=match_id))
    await cb.message.edit_reply_markup(reply_markup=dislike_reasons_kb(match_id))
    await cb.answer()


@router.callback_query(F.data.startswith("dislike_reason:"))
async def on_dislike_reason(cb: CallbackQuery) -> None:
    _, reason, mid = cb.data.split(":")
    match_id = int(mid)
    with session_scope() as s:
        if _owns_match(s, match_id, cb.from_user.id) is None:
            await cb.answer()
            return
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
        m = _owns_match(s, match_id, cb.from_user.id)
        if m is None:
            await cb.answer()
            return
        listing = s.get(Listing, m.listing_id)
        phone = (listing.contact_phone_raw if listing else None) or "—"
        url = listing.source_url if listing else ""
        s.add(Event(kind="match_btn_contact", user_id=cb.from_user.id, match_id=match_id))
    await cb.message.answer(f"📞 {phone}\n\n🔗 {url}")
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.answer()
