from __future__ import annotations

import asyncio
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

from apps.bot import keyboards as kb  # noqa: F401 (used in Task 7 /delete, /reonboard)
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
