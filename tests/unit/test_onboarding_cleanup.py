import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_track_appends_to_empty():
    from apps.bot.handlers.onboarding import _track
    state = AsyncMock()
    state.get_data.return_value = {}
    await _track(state, 42)
    state.update_data.assert_called_once_with(_del_ids=[42])


@pytest.mark.asyncio
async def test_track_appends_to_existing():
    from apps.bot.handlers.onboarding import _track
    state = AsyncMock()
    state.get_data.return_value = {"_del_ids": [1, 2]}
    await _track(state, 3, 4)
    state.update_data.assert_called_once_with(_del_ids=[1, 2, 3, 4])


@pytest.mark.asyncio
async def test_flush_calls_delete_for_each_id():
    from apps.bot.handlers.onboarding import _flush
    state = AsyncMock()
    state.get_data.return_value = {"_del_ids": [10, 20, 30]}
    bot = AsyncMock()
    await _flush(bot, chat_id=999, state=state)
    assert bot.delete_message.call_count == 3
    bot.delete_message.assert_any_call(999, 10)
    bot.delete_message.assert_any_call(999, 20)
    bot.delete_message.assert_any_call(999, 30)
    state.update_data.assert_called_once_with(_del_ids=[])


@pytest.mark.asyncio
async def test_flush_suppresses_delete_errors():
    from apps.bot.handlers.onboarding import _flush
    state = AsyncMock()
    state.get_data.return_value = {"_del_ids": [10]}
    bot = AsyncMock()
    bot.delete_message.side_effect = Exception("message not found")
    await _flush(bot, chat_id=999, state=state)  # must not raise
    state.update_data.assert_called_once_with(_del_ids=[])


@pytest.mark.asyncio
async def test_flush_empty_is_noop():
    from apps.bot.handlers.onboarding import _flush
    state = AsyncMock()
    state.get_data.return_value = {}
    bot = AsyncMock()
    await _flush(bot, chat_id=999, state=state)
    bot.delete_message.assert_not_called()
    state.update_data.assert_called_once_with(_del_ids=[])
