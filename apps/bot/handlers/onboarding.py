from __future__ import annotations

import asyncio
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from apps.bot import keyboards as kb
from apps.bot import messages as msg
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


@router.callback_query(lambda c: c.data and c.data.startswith(f"{kb.CB_SEARCH_TYPE}:"))
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

@router.callback_query(lambda c: c.data and c.data.startswith(f"{kb.CB_GENDER_PREF}:"))
async def cb_gender_pref(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    await state.update_data(gender_pref=value)
    await state.set_state(Onboarding.budget)
    await callback.message.answer(msg.ASK_BUDGET, reply_markup=kb.budget_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# budget
# ---------------------------------------------------------------------------

@router.callback_query(lambda c: c.data and c.data.startswith(f"{kb.CB_BUDGET}:"))
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

@router.callback_query(lambda c: c.data and c.data.startswith(f"{kb.CB_AREA_TOGGLE}:"))
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


@router.callback_query(lambda c: c.data == kb.CB_AREA_CUSTOM)
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


@router.callback_query(lambda c: c.data == kb.CB_AREA_DONE)
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

@router.callback_query(lambda c: c.data and c.data.startswith(f"{kb.CB_MOVE_IN}:"))
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

@router.callback_query(lambda c: c.data == kb.CB_COMMUTE_SKIP)
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

@router.callback_query(lambda c: c.data and c.data.startswith(f"{kb.CB_COMMUTE_MINUTES}:"))
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

@router.callback_query(lambda c: c.data and c.data.startswith(f"{kb.CB_COMMUTE_MODE}:"))
async def cb_commute_mode(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    await state.update_data(commute_mode=value)
    await state.set_state(Onboarding.dealbreakers)
    await state.update_data(dealbreakers=[])
    await callback.message.answer(msg.ASK_DEALBREAKERS,
                                  reply_markup=kb.dealbreakers_kb([]))
    await callback.answer()
