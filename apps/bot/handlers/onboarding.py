from __future__ import annotations

import asyncio
import logging

from aiogram import Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from apps.bot import keyboards as kb
from apps.bot import messages as msg
from apps.bot.keyboards import AXIS_LABELS
from apps.bot.states import Onboarding
from apps.shared.geo.yandex import GeocodeResult, geocode

log = logging.getLogger(__name__)
router = Router()


async def _geocode_async(query: str) -> GeocodeResult:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, geocode, query)


# ---------------------------------------------------------------------------
# /start — welcome screen
# ---------------------------------------------------------------------------

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(msg.WELCOME, reply_markup=kb.start_kb())


@router.callback_query(lambda c: c.data == kb.CB_START)
async def cb_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Onboarding.search_type)
    await callback.message.answer(msg.ASK_SEARCH_TYPE,
                                  reply_markup=kb.search_type_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# search_type
# ---------------------------------------------------------------------------

async def start_search_type(message: Message, state: FSMContext) -> None:
    await state.set_state(Onboarding.search_type)
    await message.answer(msg.ASK_SEARCH_TYPE, reply_markup=kb.search_type_kb())


@router.callback_query(Onboarding.search_type, lambda c: c.data and c.data.startswith(f"{kb.CB_SEARCH_TYPE}:"))
async def cb_search_type(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    await state.update_data(search_type=value)
    if value in ("shared_room", "looking_for_roommate"):
        await state.set_state(Onboarding.gender_pref)
        await callback.message.answer(msg.ASK_GENDER_PREF,
                                      reply_markup=kb.gender_pref_kb())
    else:
        await state.set_state(Onboarding.budget)
        await callback.message.answer(msg.ASK_BUDGET, reply_markup=kb.budget_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# gender_pref
# ---------------------------------------------------------------------------

@router.callback_query(Onboarding.gender_pref, lambda c: c.data and c.data.startswith(f"{kb.CB_GENDER_PREF}:"))
async def cb_gender_pref(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    await state.update_data(gender_pref=value)
    await state.set_state(Onboarding.budget)
    await callback.message.answer(msg.ASK_BUDGET, reply_markup=kb.budget_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# budget
# ---------------------------------------------------------------------------

@router.callback_query(Onboarding.budget, lambda c: c.data and c.data.startswith(f"{kb.CB_BUDGET}:"))
async def cb_budget(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    if parts[1] == "custom":
        await state.set_state(Onboarding.budget_custom)
        await callback.message.answer(msg.ASK_BUDGET_CUSTOM_MAX)
        await callback.answer()
        return
    lo, hi = int(parts[1]), int(parts[2])
    await state.update_data(budget_min=lo, budget_max=hi)
    await state.set_state(Onboarding.rooms)
    await callback.message.answer(msg.ASK_ROOMS, reply_markup=kb.rooms_kb())
    await callback.answer()


@router.message(Onboarding.budget_custom)
async def msg_budget_custom(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    step = data.get("_budget_step", "max")
    try:
        val = int(message.text.replace(" ", "").replace(",", ""))
    except ValueError:
        await message.answer("Введи число, например: 2500000")
        return
    if step == "max":
        await state.update_data(budget_max=val, _budget_step="min")
        await message.answer(msg.ASK_BUDGET_CUSTOM_MIN)
    else:
        await state.update_data(budget_min=val)
        await state.set_state(Onboarding.rooms)
        await message.answer(msg.ASK_ROOMS, reply_markup=kb.rooms_kb())


# ---------------------------------------------------------------------------
# rooms
# ---------------------------------------------------------------------------

@router.callback_query(lambda c: c.data and c.data.startswith(f"{kb.CB_ROOMS}:"))
async def cb_rooms(callback: CallbackQuery, state: FSMContext) -> None:
    val = int(callback.data.split(":")[1])
    await state.update_data(rooms=val if val > 0 else None)
    await state.set_state(Onboarding.areas)
    await state.update_data(areas=[])
    await callback.message.answer(msg.ASK_AREAS, reply_markup=kb.areas_kb([]))
    await callback.answer()


# ---------------------------------------------------------------------------
# areas (multi-select)
# ---------------------------------------------------------------------------

@router.callback_query(Onboarding.areas, lambda c: c.data and c.data.startswith(f"{kb.CB_AREA_TOGGLE}:"))
async def cb_area_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    area = callback.data.split(":", 1)[1]
    data = await state.get_data()
    selected: list[str] = list(data.get("areas", []))
    if area in selected:
        selected.remove(area)
    else:
        selected.append(area)
    await state.update_data(areas=selected)
    await callback.message.edit_reply_markup(reply_markup=kb.areas_kb(selected))
    await callback.answer()


@router.callback_query(Onboarding.areas, lambda c: c.data == kb.CB_AREA_CUSTOM)
async def cb_area_custom(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(_awaiting_custom_area=True)
    await callback.message.answer(msg.ASK_CUSTOM_AREA)
    await callback.answer()


@router.message(Onboarding.areas)
async def msg_custom_area(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("_awaiting_custom_area"):
        return
    selected = list(data.get("areas", []))
    selected.append(message.text.strip())
    await state.update_data(areas=selected, _awaiting_custom_area=False)
    await message.answer(
        f"Добавлен: «{message.text.strip()}»",
        reply_markup=kb.areas_kb(selected),
    )


@router.callback_query(Onboarding.areas, lambda c: c.data == kb.CB_AREA_DONE)
async def cb_area_done(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("areas"):
        await callback.answer("Выбери хотя бы один район", show_alert=True)
        return
    await state.set_state(Onboarding.move_in)
    await callback.message.answer(msg.ASK_MOVE_IN, reply_markup=kb.move_in_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# move_in
# ---------------------------------------------------------------------------

@router.callback_query(Onboarding.move_in, lambda c: c.data and c.data.startswith(f"{kb.CB_MOVE_IN}:"))
async def cb_move_in(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    await state.update_data(move_in_window=value)
    await state.set_state(Onboarding.commute_origin)
    await callback.message.answer(msg.ASK_COMMUTE_ORIGIN,
                                  reply_markup=kb.commute_skip_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# commute_origin (optional)
# ---------------------------------------------------------------------------

@router.callback_query(Onboarding.commute_origin, lambda c: c.data == kb.CB_COMMUTE_SKIP)
async def cb_commute_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(commute_origin=None)
    await state.set_state(Onboarding.dealbreakers)
    await state.update_data(dealbreakers=[])
    await callback.message.answer(msg.ASK_DEALBREAKERS,
                                  reply_markup=kb.dealbreakers_kb([]))
    await callback.answer()


@router.message(Onboarding.commute_origin)
async def msg_commute_origin(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    result = await _geocode_async(text)
    if result.lat is None:
        await message.answer(msg.GEOCODE_FAILED,
                             reply_markup=kb.commute_skip_kb())
        return
    await state.update_data(
        commute_origin=text,
        commute_origin_lat=result.lat,
        commute_origin_lng=result.lng,
    )
    await state.set_state(Onboarding.commute_minutes)
    await message.answer(msg.ASK_COMMUTE_MINUTES,
                         reply_markup=kb.commute_minutes_kb())


# ---------------------------------------------------------------------------
# commute_minutes
# ---------------------------------------------------------------------------

@router.callback_query(Onboarding.commute_minutes, lambda c: c.data and c.data.startswith(f"{kb.CB_COMMUTE_MINUTES}:"))
async def cb_commute_minutes(callback: CallbackQuery, state: FSMContext) -> None:
    val = int(callback.data.split(":")[1])
    await state.update_data(commute_max_minutes=val)
    await state.set_state(Onboarding.commute_mode)
    await callback.message.answer(msg.ASK_COMMUTE_MODE,
                                  reply_markup=kb.commute_mode_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# commute_mode
# ---------------------------------------------------------------------------

@router.callback_query(Onboarding.commute_mode, lambda c: c.data and c.data.startswith(f"{kb.CB_COMMUTE_MODE}:"))
async def cb_commute_mode(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    await state.update_data(commute_mode=value)
    await state.set_state(Onboarding.dealbreakers)
    await state.update_data(dealbreakers=[])
    await callback.message.answer(msg.ASK_DEALBREAKERS,
                                  reply_markup=kb.dealbreakers_kb([]))
    await callback.answer()


# ---------------------------------------------------------------------------
# dealbreakers (multi-select)
# ---------------------------------------------------------------------------

@router.callback_query(Onboarding.dealbreakers, lambda c: c.data and c.data.startswith(f"{kb.CB_DB_TOGGLE}:"))
async def cb_dealbreaker_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":", 1)[1]
    data = await state.get_data()
    selected: list[str] = list(data.get("dealbreakers", []))
    if key in selected:
        selected.remove(key)
    else:
        selected.append(key)
    await state.update_data(dealbreakers=selected)
    await callback.message.edit_reply_markup(
        reply_markup=kb.dealbreakers_kb(selected)
    )
    await callback.answer()


@router.callback_query(Onboarding.dealbreakers, lambda c: c.data == kb.CB_DB_DONE)
async def cb_dealbreakers_done(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Onboarding.agent_filter)
    await callback.message.answer(msg.ASK_AGENT_FILTER,
                                  reply_markup=kb.agent_filter_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# agent_filter
# ---------------------------------------------------------------------------

@router.callback_query(Onboarding.agent_filter, lambda c: c.data and c.data.startswith(f"{kb.CB_AGENT_FILTER}:"))
async def cb_agent_filter(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    await state.update_data(agent_filter=value)
    data = await state.get_data()
    axes = ["budget", "area"]
    if data.get("commute_origin"):
        axes.append("commute")
    axes += ["rooms", "furnishing"]
    await state.update_data(axis_priority={}, pending_axes=axes)
    await state.set_state(Onboarding.axis_priority)
    first_axis = axes[0]
    label = AXIS_LABELS[first_axis]
    await callback.message.answer(
        msg.ASK_AXIS_PRIORITY.format(axis=label),
        reply_markup=kb.axis_priority_kb(first_axis),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# axis_priority (iterates on itself until pending_axes is empty)
# ---------------------------------------------------------------------------

@router.callback_query(Onboarding.axis_priority, lambda c: c.data and c.data.startswith(f"{kb.CB_AXIS}:"))
async def cb_axis_priority(callback: CallbackQuery, state: FSMContext) -> None:
    _, priority, axis_key = callback.data.split(":")
    data = await state.get_data()
    axis_priority: dict = dict(data.get("axis_priority", {}))
    axis_priority[axis_key] = priority.upper()
    pending: list[str] = [a for a in data.get("pending_axes", []) if a != axis_key]
    await state.update_data(axis_priority=axis_priority, pending_axes=pending)
    if pending:
        next_axis = pending[0]
        label = AXIS_LABELS[next_axis]
        await callback.message.answer(
            msg.ASK_AXIS_PRIORITY.format(axis=label),
            reply_markup=kb.axis_priority_kb(next_axis),
        )
    else:
        await state.set_state(Onboarding.free_text_wall)
        await callback.message.answer(msg.FREE_TEXT_WALL,
                                      reply_markup=kb.free_text_wall_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# free_text_wall
# ---------------------------------------------------------------------------

@router.callback_query(Onboarding.free_text_wall, lambda c: c.data and c.data.startswith(f"{kb.CB_FREE_TEXT_WALL}:"))
async def cb_free_text_wall(callback: CallbackQuery, state: FSMContext) -> None:
    choice = callback.data.split(":")[1]
    if choice == "skip":
        await _trigger_done(callback.message, state)
    else:
        await state.set_state(Onboarding.free_text_1)
        await callback.message.answer(msg.FREE_TEXT_1,
                                      reply_markup=kb.free_text_skip_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# free_text_1 / 2 / 3 — text input or skip
# ---------------------------------------------------------------------------

@router.message(Onboarding.free_text_1)
async def msg_free_text_1(message: Message, state: FSMContext) -> None:
    await state.update_data(tradeoff_hint_text=message.text.strip())
    await state.set_state(Onboarding.free_text_2)
    await message.answer(msg.FREE_TEXT_2, reply_markup=kb.free_text_skip_kb())


@router.message(Onboarding.free_text_2)
async def msg_free_text_2(message: Message, state: FSMContext) -> None:
    await state.update_data(unacceptable_text=message.text.strip())
    await state.set_state(Onboarding.free_text_3)
    await message.answer(msg.FREE_TEXT_3, reply_markup=kb.free_text_skip_kb())


@router.message(Onboarding.free_text_3)
async def msg_free_text_3(message: Message, state: FSMContext) -> None:
    await state.update_data(instant_reject_text=message.text.strip())
    await _trigger_done(message, state)


@router.callback_query(StateFilter(Onboarding.free_text_1, Onboarding.free_text_2, Onboarding.free_text_3), lambda c: c.data == kb.CB_FREE_TEXT_SKIP)
async def cb_free_text_skip(callback: CallbackQuery, state: FSMContext) -> None:
    current = await state.get_state()
    if current == Onboarding.free_text_1:
        await state.set_state(Onboarding.free_text_2)
        await callback.message.answer(msg.FREE_TEXT_2,
                                      reply_markup=kb.free_text_skip_kb())
    elif current == Onboarding.free_text_2:
        await state.set_state(Onboarding.free_text_3)
        await callback.message.answer(msg.FREE_TEXT_3,
                                      reply_markup=kb.free_text_skip_kb())
    else:
        await _trigger_done(callback.message, state)
    await callback.answer()


# ---------------------------------------------------------------------------
# DONE — background profile build
# ---------------------------------------------------------------------------

async def _trigger_done(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    await message.answer(msg.BUILDING_PROFILE)
    asyncio.create_task(_build_profile_async(message, data))


async def _build_profile_async(message: Message, data: dict) -> None:
    loop = asyncio.get_running_loop()
    tg_user_id = message.from_user.id
    tg_username = getattr(message.from_user, "username", None)

    from apps.shared.llm.gemini import GeminiClient
    from apps.shared.enrichment.embed import build_user_pref_text
    from apps.shared.db import session_scope
    from apps.shared.models import User, Event
    from apps.shared.enums import UserState
    from sqlalchemy import select
    from datetime import UTC, datetime

    gemini = GeminiClient()

    # 1. Extract dealbreaker keywords from instant_reject_text
    dealbreaker_keywords: list[str] = []
    instant_reject = data.get("instant_reject_text")
    if instant_reject:
        try:
            schema = {
                "type": "object",
                "properties": {
                    "keywords": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["keywords"],
            }
            prompt = (
                f"Extract short rejection keywords from this apartment search note. "
                f"Return a JSON list of strings (1-3 words each, Russian).\n\n{instant_reject}"
            )
            result = await loop.run_in_executor(
                None, lambda: gemini.generate_json(prompt, schema)
            )
            dealbreaker_keywords = result.get("keywords", [])
        except Exception:
            log.warning("Keyword extraction failed; continuing without keywords")

    # 2. Build preference embedding
    pref_text = build_user_pref_text(
        search_type=data.get("search_type"),
        budget_min=data.get("budget_min"),
        budget_max=data.get("budget_max"),
        rooms=data.get("rooms"),
        areas=data.get("areas", []),
        commute_origin=data.get("commute_origin"),
        commute_max_minutes=data.get("commute_max_minutes"),
        commute_mode=data.get("commute_mode"),
        dealbreakers=data.get("dealbreakers", []),
        tradeoff_hint_text=data.get("tradeoff_hint_text"),
        unacceptable_text=data.get("unacceptable_text"),
    )
    embedding: list[float] | None = None
    try:
        embedding = await loop.run_in_executor(None, gemini.embed, pref_text)
    except Exception:
        log.warning("Embedding build failed; user marked active with null embedding")

    # 3. Upsert User row
    def _upsert(u_data: dict, keywords: list[str], emb: list[float] | None) -> None:
        with session_scope() as s:
            row = s.execute(
                select(User).where(User.tg_user_id == u_data["tg_user_id"])
            ).scalar_one_or_none()
            if row is None:
                row = User(tg_user_id=u_data["tg_user_id"])
                s.add(row)
            row.tg_username = u_data.get("tg_username")
            row.search_type = u_data.get("search_type")
            row.gender_pref = u_data.get("gender_pref")
            row.agent_filter = u_data.get("agent_filter")
            row.budget_min = u_data.get("budget_min")
            row.budget_max = u_data.get("budget_max")
            row.rooms = u_data.get("rooms")
            row.areas = u_data.get("areas", [])
            row.move_in_window = u_data.get("move_in_window")
            row.commute_origin = u_data.get("commute_origin")
            row.commute_origin_lat = u_data.get("commute_origin_lat")
            row.commute_origin_lng = u_data.get("commute_origin_lng")
            row.commute_max_minutes = u_data.get("commute_max_minutes")
            row.commute_mode = u_data.get("commute_mode")
            row.dealbreakers = u_data.get("dealbreakers", [])
            row.dealbreaker_keywords = keywords
            row.axis_priority = u_data.get("axis_priority", {})
            row.tradeoff_hint_text = u_data.get("tradeoff_hint_text")
            row.unacceptable_text = u_data.get("unacceptable_text")
            row.instant_reject_text = u_data.get("instant_reject_text")
            row.preference_embedding = emb
            row.state = UserState.ACTIVE
            row.onboarded_at = datetime.now(UTC)
            s.add(Event(kind="onboarding_completed", user_id=row.tg_user_id))

    await loop.run_in_executor(
        None,
        _upsert,
        {"tg_user_id": tg_user_id, "tg_username": tg_username, **data},
        dealbreaker_keywords,
        embedding,
    )
    await message.answer(msg.ONBOARDING_DONE)
