import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from apps.bot.states import Onboarding


async def make_ctx(user_id: int = 123) -> FSMContext:
    key = StorageKey(bot_id=1, user_id=user_id, chat_id=user_id)
    return FSMContext(storage=MemoryStorage(), key=key)


def make_cb(data: str, user_id: int = 123) -> MagicMock:
    cb = AsyncMock()
    cb.data = data
    cb.from_user = MagicMock(id=user_id, username="t")
    cb.message = AsyncMock()
    cb.answer = AsyncMock()
    return cb


def make_msg(text: str = "hi", user_id: int = 123) -> MagicMock:
    m = AsyncMock()
    m.text = text
    m.from_user = MagicMock(id=user_id, username="t")
    m.answer = AsyncMock()
    return m


@pytest.mark.asyncio
async def test_start_sends_welcome():
    from apps.bot.handlers.onboarding import cmd_start
    m = make_msg("/start")
    ctx = await make_ctx()
    await cmd_start(m, ctx)
    m.answer.assert_called_once()
    assert "Scout" in m.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_search_type_whole_apt_skips_gender():
    from apps.bot.handlers.onboarding import cb_search_type
    cb = make_cb("st:whole_apt_family")
    ctx = await make_ctx()
    await cb_search_type(cb, ctx)
    state = await ctx.get_state()
    data = await ctx.get_data()
    assert state == Onboarding.budget
    assert data["search_type"] == "whole_apt_family"


@pytest.mark.asyncio
async def test_search_type_shared_room_goes_to_gender():
    from apps.bot.handlers.onboarding import cb_search_type
    cb = make_cb("st:shared_room")
    ctx = await make_ctx()
    await cb_search_type(cb, ctx)
    state = await ctx.get_state()
    assert state == Onboarding.gender_pref


@pytest.mark.asyncio
async def test_budget_preset_stored():
    from apps.bot.handlers.onboarding import cb_budget
    cb = make_cb("budget:1500000:2500000")
    ctx = await make_ctx()
    await ctx.set_state(Onboarding.budget)
    await cb_budget(cb, ctx)
    data = await ctx.get_data()
    assert data["budget_min"] == 1_500_000
    assert data["budget_max"] == 2_500_000
    state = await ctx.get_state()
    assert state == Onboarding.rooms


@pytest.mark.asyncio
async def test_commute_skip_jumps_to_dealbreakers():
    from apps.bot.handlers.onboarding import cb_commute_skip
    cb = make_cb("commute_skip")
    ctx = await make_ctx()
    await ctx.set_state(Onboarding.commute_origin)
    await cb_commute_skip(cb, ctx)
    state = await ctx.get_state()
    data = await ctx.get_data()
    assert state == Onboarding.dealbreakers
    assert data.get("commute_origin") is None


@pytest.mark.asyncio
async def test_commute_origin_text_geocodes_and_advances():
    from apps.bot.handlers.onboarding import msg_commute_origin
    from apps.shared.geo.yandex import GeocodeResult
    m = make_msg("TUIT university")
    ctx = await make_ctx()
    await ctx.set_state(Onboarding.commute_origin)
    fake_result = GeocodeResult(lat=41.3, lng=69.2, matched_text="TUIT")
    with patch("apps.bot.handlers.onboarding._geocode_async",
               return_value=fake_result):
        await msg_commute_origin(m, ctx)
    state = await ctx.get_state()
    data = await ctx.get_data()
    assert state == Onboarding.commute_minutes
    assert data["commute_origin"] == "TUIT university"
    assert data["commute_origin_lat"] == 41.3
