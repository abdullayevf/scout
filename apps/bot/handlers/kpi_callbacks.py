"""Handlers for KPI chase responses and weekly check-in."""

import logging
from datetime import UTC, datetime, timedelta

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select

from apps.shared.db import session_scope
from apps.shared.enums import MatchState, UserState
from apps.shared.models import Event, Match, User

log = logging.getLogger(__name__)
router = Router(name="kpi_callbacks")


def _get_match_for_user(
    s, match_id: int, tg_user_id: int
) -> tuple[Match, User] | tuple[None, None]:
    m = s.get(Match, match_id)
    if m is None:
        return None, None
    u = s.execute(select(User).where(User.tg_user_id == tg_user_id)).scalar_one_or_none()
    if u is None or u.id != m.user_id:
        return None, None
    return m, u


@router.callback_query(F.data.startswith("chase48y:"))
async def on_chase_48h_yes(cb: CallbackQuery) -> None:
    match_id = int(cb.data.split(":", 1)[1])
    with session_scope() as s:
        m, u = _get_match_for_user(s, match_id, cb.from_user.id)
        if m is None:
            await cb.answer()
            return
        if m.contacted_at is None:
            m.contacted_at = datetime.now(UTC)
        if m.state not in (MatchState.CONTACTED, MatchState.RENTED):
            m.state = MatchState.CONTACTED
        m.chase_5d_due_at = datetime.now(UTC) + timedelta(days=5)
        s.add(Event(kind="chase_48h_yes", user_id=u.id, match_id=match_id))
        s.flush()
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.edit_text((cb.message.text or "") + "\n\n✅ Отлично! Удачи с переговорами.")
    await cb.answer()


@router.callback_query(F.data.startswith("chase48n:"))
async def on_chase_48h_no(cb: CallbackQuery) -> None:
    match_id = int(cb.data.split(":", 1)[1])
    with session_scope() as s:
        m, u = _get_match_for_user(s, match_id, cb.from_user.id)
        if m is None:
            await cb.answer()
            return
        s.add(Event(kind="chase_48h_no", user_id=u.id, match_id=match_id))
        s.flush()
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.edit_text((cb.message.text or "") + "\n\n👍 Понял. Продолжаем искать!")
    await cb.answer()


@router.callback_query(F.data.startswith("chase5y:"))
async def on_chase_5d_yes(cb: CallbackQuery) -> None:
    from apps.bot.keyboards import rented_pause_kb
    match_id = int(cb.data.split(":", 1)[1])
    with session_scope() as s:
        m, u = _get_match_for_user(s, match_id, cb.from_user.id)
        if m is None:
            await cb.answer()
            return
        m.state = MatchState.RENTED
        m.rented_at = datetime.now(UTC)
        u.state = UserState.SUCCESS
        u.success_at = datetime.now(UTC)
        s.add(Event(kind="chase_5d_yes", user_id=u.id, match_id=match_id))
        s.flush()
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(
        "🎉 Поздравляем! Вы нашли квартиру!\n\nХотите приостановить уведомления?",
        reply_markup=rented_pause_kb(),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("chase5n:"))
async def on_chase_5d_no(cb: CallbackQuery) -> None:
    match_id = int(cb.data.split(":", 1)[1])
    with session_scope() as s:
        m, u = _get_match_for_user(s, match_id, cb.from_user.id)
        if m is None:
            await cb.answer()
            return
        s.add(Event(kind="chase_5d_no", user_id=u.id, match_id=match_id))
        s.flush()
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.edit_text((cb.message.text or "") + "\n\n👍 Ещё ищете — продолжаем!")
    await cb.answer()


@router.callback_query(F.data == "rented:pause")
async def on_rented_pause(cb: CallbackQuery) -> None:
    with session_scope() as s:
        u = s.execute(
            select(User).where(User.tg_user_id == cb.from_user.id)
        ).scalar_one_or_none()
        if u is None:
            await cb.answer()
            return
        u.state = UserState.PAUSED
        s.add(Event(kind="rented_pause", user_id=u.id))
        s.flush()
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.edit_text(
        "⏸ Уведомления приостановлены. Используйте /resume чтобы возобновить поиск."
    )
    await cb.answer()


@router.callback_query(F.data == "rented:continue")
async def on_rented_continue(cb: CallbackQuery) -> None:
    with session_scope() as s:
        u = s.execute(
            select(User).where(User.tg_user_id == cb.from_user.id)
        ).scalar_one_or_none()
        if u is None:
            await cb.answer()
            return
        s.add(Event(kind="rented_continue", user_id=u.id))
        s.flush()
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.edit_text((cb.message.text or "") + "\n\n✅ Отлично! Продолжаем поиск.")
    await cb.answer()


@router.callback_query(F.data == "wcheckin:searching")
async def on_weekly_searching(cb: CallbackQuery) -> None:
    with session_scope() as s:
        u = s.execute(
            select(User).where(User.tg_user_id == cb.from_user.id)
        ).scalar_one_or_none()
        if u is None:
            await cb.answer()
            return
        s.add(Event(kind="weekly_checkin_searching", user_id=u.id))
        s.flush()
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.edit_text((cb.message.text or "") + "\n\n🔍 Продолжаем поиск!")
    await cb.answer()


@router.callback_query(F.data == "wcheckin:found")
async def on_weekly_found(cb: CallbackQuery) -> None:
    from apps.bot.keyboards import rented_pause_kb
    with session_scope() as s:
        u = s.execute(
            select(User).where(User.tg_user_id == cb.from_user.id)
        ).scalar_one_or_none()
        if u is None:
            await cb.answer()
            return
        u.state = UserState.SUCCESS
        u.success_at = datetime.now(UTC)
        s.add(Event(kind="weekly_checkin_found", user_id=u.id))
        s.flush()
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(
        "🎉 Поздравляем! Хотите приостановить уведомления?",
        reply_markup=rented_pause_kb(),
    )
    await cb.answer()


@router.callback_query(F.data == "wcheckin:quit")
async def on_weekly_quit(cb: CallbackQuery) -> None:
    with session_scope() as s:
        u = s.execute(
            select(User).where(User.tg_user_id == cb.from_user.id)
        ).scalar_one_or_none()
        if u is None:
            await cb.answer()
            return
        u.state = UserState.DELETED
        s.add(Event(kind="weekly_checkin_quit", user_id=u.id))
        s.flush()
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.edit_text("🚪 Понял. Уведомления отключены. Удачи!")
    await cb.answer()
