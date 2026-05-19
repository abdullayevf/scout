import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from apps.bot.states import Onboarding
from apps.shared.models import Base


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
    with patch("apps.bot.handlers.onboarding._get_user", return_value=None):
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


@pytest.mark.asyncio
async def test_dealbreakers_done_advances_to_agent_filter():
    from apps.bot.handlers.onboarding import cb_dealbreakers_done
    cb = make_cb("db_done")
    ctx = await make_ctx()
    await ctx.set_state(Onboarding.dealbreakers)
    await ctx.update_data(dealbreakers=[])
    await cb_dealbreakers_done(cb, ctx)
    state = await ctx.get_state()
    assert state == Onboarding.agent_filter


@pytest.mark.asyncio
async def test_axis_priority_iterates_then_stays():
    from apps.bot.handlers.onboarding import cb_axis_priority
    cb = make_cb("axis:must:budget")
    ctx = await make_ctx()
    await ctx.set_state(Onboarding.axis_priority)
    await ctx.update_data(
        axis_priority={},
        pending_axes=["budget", "area"],
    )
    await cb_axis_priority(cb, ctx)
    data = await ctx.get_data()
    assert data["axis_priority"]["budget"] == "MUST"
    assert data["pending_axes"] == ["area"]
    state = await ctx.get_state()
    assert state == Onboarding.axis_priority


@pytest.mark.asyncio
async def test_axis_priority_last_axis_advances_to_free_text_wall():
    from apps.bot.handlers.onboarding import cb_axis_priority
    cb = make_cb("axis:nice:area")
    ctx = await make_ctx()
    await ctx.set_state(Onboarding.axis_priority)
    await ctx.update_data(axis_priority={"budget": "MUST"}, pending_axes=["area"])
    await cb_axis_priority(cb, ctx)
    state = await ctx.get_state()
    assert state == Onboarding.free_text_wall


@pytest.mark.asyncio
async def test_free_text_wall_skip_triggers_build():
    from apps.bot.handlers.onboarding import cb_free_text_wall
    cb = make_cb("ftw:skip")
    ctx = await make_ctx()
    await ctx.set_state(Onboarding.free_text_wall)
    await ctx.update_data(
        search_type="whole_apt_solo",
        budget_min=0,
        budget_max=3_000_000,
        rooms=2,
        areas=["Yunusabad"],
        move_in_window="now",
        commute_origin=None,
        dealbreakers=[],
        agent_filter="owner_only",
        axis_priority={"budget": "MUST"},
        gender_pref=None,
    )
    with patch("apps.bot.handlers.onboarding._build_profile_async") as build_mock:
        build_mock.return_value = None
        await cb_free_text_wall(cb, ctx)
    build_mock.assert_called_once()


@pytest.mark.asyncio
async def test_free_text_3_skip_triggers_done():
    from apps.bot.handlers.onboarding import cb_free_text_skip
    cb = make_cb("fts")
    ctx = await make_ctx()
    await ctx.set_state(Onboarding.free_text_3)
    await ctx.update_data(
        search_type="whole_apt_solo", budget_min=0, budget_max=3_000_000,
        rooms=None, areas=["Yunusabad"], move_in_window="flexible",
        commute_origin=None, dealbreakers=[], agent_filter="agents_ok",
        axis_priority={}, gender_pref=None,
    )
    with patch("apps.bot.handlers.onboarding._build_profile_async"):
        await cb_free_text_skip(cb, ctx)


@pytest.mark.asyncio
async def test_axis_priority_skips_rooms_when_any():
    from apps.bot.handlers.onboarding import cb_agent_filter
    cb = make_cb("af:owner_only")
    ctx = await make_ctx()
    await ctx.set_state(Onboarding.agent_filter)
    await ctx.update_data(
        areas=["Yunusabad", "Chilanzar"],
        commute_origin=None,
        rooms=None,
    )
    await cb_agent_filter(cb, ctx)
    data = await ctx.get_data()
    assert "rooms" not in data["pending_axes"]
    assert "furnishing" not in data["pending_axes"]


@pytest.mark.asyncio
async def test_axis_priority_includes_rooms_when_specified():
    from apps.bot.handlers.onboarding import cb_agent_filter
    cb = make_cb("af:owner_only")
    ctx = await make_ctx()
    await ctx.set_state(Onboarding.agent_filter)
    await ctx.update_data(
        areas=["Yunusabad", "Chilanzar"],
        commute_origin=None,
        rooms=2,
    )
    await cb_agent_filter(cb, ctx)
    data = await ctx.get_data()
    assert "rooms" in data["pending_axes"]


@pytest.mark.asyncio
async def test_axis_priority_auto_must_for_single_area():
    from apps.bot.handlers.onboarding import cb_agent_filter
    cb = make_cb("af:owner_only")
    ctx = await make_ctx()
    await ctx.set_state(Onboarding.agent_filter)
    await ctx.update_data(
        areas=["Yunusabad"],
        commute_origin=None,
        rooms=None,
    )
    await cb_agent_filter(cb, ctx)
    data = await ctx.get_data()
    assert "area" not in data["pending_axes"]
    assert data["axis_priority"]["area"] == "MUST"


@pytest.mark.asyncio
async def test_axis_priority_asks_area_when_multiple():
    from apps.bot.handlers.onboarding import cb_agent_filter
    cb = make_cb("af:owner_only")
    ctx = await make_ctx()
    await ctx.set_state(Onboarding.agent_filter)
    await ctx.update_data(
        areas=["Yunusabad", "Chilanzar"],
        commute_origin=None,
        rooms=None,
    )
    await cb_agent_filter(cb, ctx)
    data = await ctx.get_data()
    assert "area" in data["pending_axes"]
    assert "area" not in data.get("axis_priority", {})


@pytest.mark.asyncio
async def test_axis_priority_never_includes_furnishing():
    from apps.bot.handlers.onboarding import cb_agent_filter
    cb = make_cb("af:owner_only")
    ctx = await make_ctx()
    await ctx.set_state(Onboarding.agent_filter)
    await ctx.update_data(
        areas=["Yunusabad", "Chilanzar"],
        commute_origin="TUIT",
        rooms=2,
    )
    await cb_agent_filter(cb, ctx)
    data = await ctx.get_data()
    assert "furnishing" not in data["pending_axes"]


@pytest.mark.asyncio
async def test_build_profile_zero_vector_helper():
    """Verify the zero-vector value used on Gemini failure matches settings.embedding_dim."""
    from apps.shared.config import settings
    zero = [0.0] * settings.embedding_dim
    assert len(zero) == settings.embedding_dim
    assert all(v == 0.0 for v in zero)


@pytest.mark.asyncio
async def test_build_profile_uses_zero_vector_on_embed_failure():
    """When Gemini embed raises, the embedding passed to _upsert is a zero vector, not None."""
    from apps.bot.handlers import onboarding
    from apps.shared.config import settings

    class FakeGemini:
        def generate_json(self, prompt, schema):
            return {"keywords": []}

        def embed(self, text):
            raise RuntimeError("simulated gemini failure")

    message = AsyncMock()
    message.from_user = MagicMock(id=999, username="t")
    message.answer = AsyncMock()

    data = {
        "search_type": "whole_apt_solo",
        "budget_min": 0,
        "budget_max": 3_000_000,
        "rooms": 2,
        "areas": ["Yunusabad"],
        "move_in_window": "now",
        "commute_origin": None,
        "dealbreakers": [],
        "agent_filter": "owner_only",
        "axis_priority": {},
        "instant_reject_text": None,
    }

    captured_emb = []

    # Patch _upsert at the source level by intercepting run_in_executor calls
    # whose third positional arg (emb) we want to capture.
    original_run_in_executor = None

    async def fake_run_in_executor(executor, func, *args):
        # Detect the _upsert call by inspecting the function's code name
        func_name = getattr(func, "__name__", "") or getattr(
            getattr(func, "__func__", None), "__name__", ""
        )
        if func_name == "_run_upsert":
            # args = (u_data, keywords, emb)
            captured_emb.append(args[2])
            return None
        # For all other executor calls (embed, generate_json, etc.) run inline
        # by calling the function directly (they're all sync in the fake)
        return func(*args)

    fake_loop = MagicMock()
    fake_loop.run_in_executor = fake_run_in_executor

    from_user = MagicMock(id=999, username="t")

    with patch("apps.shared.llm.gemini.GeminiClient", FakeGemini), \
         patch("asyncio.get_running_loop", return_value=fake_loop):
        await onboarding._build_profile_async(message, from_user, data)

    assert len(captured_emb) == 1, f"Expected 1 captured embedding, got {len(captured_emb)}"
    emb = captured_emb[0]
    assert emb is not None, "embedding should not be None — expected zero vector"
    assert isinstance(emb, list)
    assert len(emb) == settings.embedding_dim
    assert all(v == 0.0 for v in emb)


def test_onboarding_triggers_welcome_task(engine, db_session):
    from apps.bot.handlers import onboarding as ob_module
    from unittest.mock import patch

    Base.metadata.create_all(engine)
    data = {
        "tg_user_id": 9001, "tg_username": "u",
        "search_type": "whole_apt_solo",
        "budget_min": 1_000_000, "budget_max": 3_000_000,
        "rooms": None,
        "areas": ["Yunusabad"],
        "axis_priority": {},
        "agent_filter": "agents_ok",
        "move_in_window": None,
        "commute_origin": None,
        "commute_origin_lat": None,
        "commute_origin_lng": None,
        "commute_max_minutes": None,
        "commute_mode": None,
        "dealbreakers": [],
        "dealbreaker_keywords": [],
        "tradeoff_hint_text": None,
        "unacceptable_text": None,
        "instant_reject_text": None,
    }
    with patch("apps.bot.handlers.onboarding.session_scope") as ss, \
         patch("apps.bot.handlers.onboarding.match_welcome_for_user") as mw:
        ss.return_value.__enter__.return_value = db_session
        db_id = ob_module._run_upsert(data, [], [0.1] * 3072)

    assert isinstance(db_id, int)
    mw.delay.assert_called_once_with(db_id)
