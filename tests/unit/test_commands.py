from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.shared.enums import UserState


def make_message(user_id: int = 123, text: str = "/help") -> MagicMock:
    msg = AsyncMock()
    msg.text = text
    msg.from_user = MagicMock(id=user_id, username="tester")
    msg.answer = AsyncMock()
    return msg


def make_user_row(state: str = UserState.ACTIVE):
    u = MagicMock()
    u.state = state
    u.id = 1
    return u


@pytest.mark.asyncio
async def test_help_always_works():
    from apps.bot.handlers.commands import cmd_help
    msg = make_message()
    await cmd_help(msg)
    msg.answer.assert_called_once()
    text = msg.answer.call_args[0][0]
    assert "/settings" in text


@pytest.mark.asyncio
async def test_pause_sets_state_paused():
    from apps.bot.handlers.commands import cmd_pause
    msg = make_message()
    user = make_user_row(UserState.ACTIVE)
    with patch("apps.bot.handlers.commands._get_user", return_value=user), \
         patch("apps.bot.handlers.commands._save_user") as save_mock:
        await cmd_pause(msg)
        assert user.state == UserState.PAUSED
        save_mock.assert_called_once_with(user)
        msg.answer.assert_called_once()


@pytest.mark.asyncio
async def test_pause_already_paused():
    from apps.bot.handlers.commands import cmd_pause
    msg = make_message()
    user = make_user_row(UserState.PAUSED)
    with patch("apps.bot.handlers.commands._get_user", return_value=user):
        await cmd_pause(msg)
        text = msg.answer.call_args[0][0]
        assert "паузе" in text.lower()


@pytest.mark.asyncio
async def test_resume_sets_state_active():
    from apps.bot.handlers.commands import cmd_resume
    msg = make_message()
    user = make_user_row(UserState.PAUSED)
    with patch("apps.bot.handlers.commands._get_user", return_value=user), \
         patch("apps.bot.handlers.commands._save_user") as save_mock:
        await cmd_resume(msg)
        assert user.state == UserState.ACTIVE
        save_mock.assert_called_once()


@pytest.mark.asyncio
async def test_guard_blocks_unknown_user():
    from apps.bot.handlers.commands import require_active_user
    msg = make_message()
    with patch("apps.bot.handlers.commands._get_user", return_value=None):
        result = await require_active_user(msg)
        assert result is False
        msg.answer.assert_called_once()
        assert "/start" in msg.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_delete_confirm_flow():
    from apps.bot.handlers.commands import cmd_delete, cb_delete_yes
    msg2 = make_message(text="/delete")
    user = make_user_row(UserState.ACTIVE)
    with patch("apps.bot.handlers.commands._get_user", return_value=user):
        await cmd_delete(msg2)
        text = msg2.answer.call_args[0][0]
        assert "Удалить" in text

    cb = AsyncMock()
    cb.from_user = MagicMock(id=123)
    cb.message = AsyncMock()
    cb.answer = AsyncMock()
    with patch("apps.bot.handlers.commands._get_user", return_value=user), \
         patch("apps.bot.handlers.commands._wipe_user") as wipe_mock, \
         patch("apps.bot.handlers.commands._write_event"):
        await cb_delete_yes(cb)
        wipe_mock.assert_called_once_with(user)
        cb.message.answer.assert_called_once()


@pytest.mark.asyncio
async def test_reonboard_confirm_clears_state():
    from apps.bot.handlers.commands import cb_reonboard_yes
    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.storage.base import StorageKey
    from aiogram.fsm.storage.memory import MemoryStorage

    storage = MemoryStorage()
    key = StorageKey(bot_id=1, user_id=123, chat_id=123)
    ctx = FSMContext(storage=storage, key=key)
    await ctx.update_data({"search_type": "whole_apt_solo"})

    cb = AsyncMock()
    cb.from_user = MagicMock(id=123, username="t")
    cb.message = AsyncMock()
    cb.answer = AsyncMock()

    user = make_user_row(UserState.ACTIVE)
    with patch("apps.bot.handlers.commands._get_user", return_value=user), \
         patch("apps.bot.handlers.commands._reset_user_prefs") as reset_mock, \
         patch("apps.bot.handlers.onboarding.start_search_type"):
        await cb_reonboard_yes(cb, ctx)
        reset_mock.assert_called_once_with(user)
