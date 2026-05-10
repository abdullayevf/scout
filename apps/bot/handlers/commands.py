from __future__ import annotations

import asyncio
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from apps.bot import keyboards as kb
from apps.bot import messages as msg
from apps.shared.db import session_scope
from apps.shared.enums import UserState
from apps.shared.models import Event, User

log = logging.getLogger(__name__)
router = Router()


# ---------------------------------------------------------------------------
# Internal helpers (sync, called via run_in_executor from async handlers)
# ---------------------------------------------------------------------------

def _get_user(tg_user_id: int) -> User | None:
    with session_scope() as s:
        return s.execute(
            select(User).where(User.tg_user_id == tg_user_id)
        ).scalar_one_or_none()


def _save_user(user: User) -> None:
    with session_scope() as s:
        s.merge(user)


def _write_event(kind: str, user_id: int | None) -> None:
    with session_scope() as s:
        s.add(Event(kind=kind, user_id=user_id))


# ---------------------------------------------------------------------------
# Guard helper — returns False and replies if user not found or deleted
# ---------------------------------------------------------------------------

async def require_active_user(message: Message) -> bool:
    loop = asyncio.get_running_loop()
    user = await loop.run_in_executor(None, _get_user, message.from_user.id)
    if user is None or user.state == UserState.DELETED:
        await message.answer(msg.NOT_ONBOARDED)
        return False
    return True


# ---------------------------------------------------------------------------
# /help — always works regardless of user state
# ---------------------------------------------------------------------------

@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(msg.HELP)


# ---------------------------------------------------------------------------
# /pause
# ---------------------------------------------------------------------------

@router.message(Command("pause"))
async def cmd_pause(message: Message) -> None:
    loop = asyncio.get_running_loop()
    user = await loop.run_in_executor(None, _get_user, message.from_user.id)
    if user is None or user.state == UserState.DELETED:
        await message.answer(msg.NOT_ONBOARDED)
        return
    if user.state == UserState.PAUSED:
        await message.answer(msg.PAUSE_ALREADY)
        return
    user.state = UserState.PAUSED
    user.paused_until = None
    await loop.run_in_executor(None, _save_user, user)
    await message.answer(msg.PAUSE_OK)


# ---------------------------------------------------------------------------
# /resume
# ---------------------------------------------------------------------------

@router.message(Command("resume"))
async def cmd_resume(message: Message) -> None:
    loop = asyncio.get_running_loop()
    user = await loop.run_in_executor(None, _get_user, message.from_user.id)
    if user is None or user.state == UserState.DELETED:
        await message.answer(msg.NOT_ONBOARDED)
        return
    if user.state != UserState.PAUSED:
        await message.answer(msg.RESUME_NOT_PAUSED)
        return
    user.state = UserState.ACTIVE
    user.paused_until = None
    await loop.run_in_executor(None, _save_user, user)
    await message.answer(msg.RESUME_OK)


# ---------------------------------------------------------------------------
# /delete
# ---------------------------------------------------------------------------

def _wipe_user(user: User) -> None:
    with session_scope() as s:
        row = s.merge(user)
        row.state = UserState.DELETED
        row.search_type = None
        row.gender_pref = None
        row.agent_filter = None
        row.budget_min = None
        row.budget_max = None
        row.rooms = None
        row.areas = []
        row.move_in_window = None
        row.commute_origin = None
        row.commute_origin_lat = None
        row.commute_origin_lng = None
        row.commute_max_minutes = None
        row.commute_mode = None
        row.dealbreakers = []
        row.dealbreaker_keywords = []
        row.axis_priority = {}
        row.tradeoff_hint_text = None
        row.unacceptable_text = None
        row.instant_reject_text = None
        row.preference_embedding = None
        row.negative_area_mask = []
        row.distrust_set = []
        row.seen_set = []
        row.top_1pct_threshold = None


@router.message(Command("delete"))
async def cmd_delete(message: Message) -> None:
    if not await require_active_user(message):
        return
    await message.answer(
        msg.DELETE_CONFIRM,
        reply_markup=kb.confirm_kb(
            yes_data=kb.CB_DELETE_YES,
            no_data=kb.CB_DELETE_NO,
            yes_label="Да, удалить",
            no_label="Отмена",
        ),
    )


@router.callback_query(lambda c: c.data == kb.CB_DELETE_YES)
async def cb_delete_yes(callback: CallbackQuery) -> None:
    loop = asyncio.get_running_loop()
    user = await loop.run_in_executor(None, _get_user, callback.from_user.id)
    if user:
        await loop.run_in_executor(None, _wipe_user, user)
        await loop.run_in_executor(
            None, _write_event, "user_deleted", user.id
        )
    await callback.message.answer(msg.DELETE_DONE)
    await callback.answer()


@router.callback_query(lambda c: c.data == kb.CB_DELETE_NO)
async def cb_delete_no(callback: CallbackQuery) -> None:
    await callback.message.answer(msg.DELETE_CANCELLED)
    await callback.answer()


# ---------------------------------------------------------------------------
# /reonboard
# ---------------------------------------------------------------------------

def _reset_user_prefs(user: User) -> None:
    with session_scope() as s:
        row = s.merge(user)
        row.state = UserState.ONBOARDING
        row.search_type = None
        row.gender_pref = None
        row.agent_filter = None
        row.budget_min = None
        row.budget_max = None
        row.rooms = None
        row.areas = []
        row.move_in_window = None
        row.commute_origin = None
        row.commute_origin_lat = None
        row.commute_origin_lng = None
        row.commute_max_minutes = None
        row.commute_mode = None
        row.dealbreakers = []
        row.dealbreaker_keywords = []
        row.axis_priority = {}
        row.tradeoff_hint_text = None
        row.unacceptable_text = None
        row.instant_reject_text = None
        row.preference_embedding = None
        row.onboarded_at = None


@router.message(Command("reonboard"))
async def cmd_reonboard(message: Message) -> None:
    if not await require_active_user(message):
        return
    await message.answer(
        msg.REONBOARD_CONFIRM,
        reply_markup=kb.confirm_kb(
            yes_data=kb.CB_REONBOARD_YES,
            no_data=kb.CB_REONBOARD_NO,
        ),
    )


@router.callback_query(lambda c: c.data == kb.CB_REONBOARD_YES)
async def cb_reonboard_yes(callback: CallbackQuery, state: FSMContext) -> None:
    loop = asyncio.get_running_loop()
    user = await loop.run_in_executor(None, _get_user, callback.from_user.id)
    if user:
        await loop.run_in_executor(None, _reset_user_prefs, user)
    await state.clear()
    from apps.bot.handlers.onboarding import start_search_type
    await start_search_type(callback.message, state)
    await callback.answer()


@router.callback_query(lambda c: c.data == kb.CB_REONBOARD_NO)
async def cb_reonboard_no(callback: CallbackQuery) -> None:
    await callback.message.answer(msg.REONBOARD_CANCELLED)
    await callback.answer()
