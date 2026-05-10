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
