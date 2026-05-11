from __future__ import annotations

import asyncio
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from apps.bot import keyboards as kb
from apps.bot import messages as msg
from apps.bot.handlers.commands import _get_user, require_active_user
from apps.bot.states import Settings

log = logging.getLogger(__name__)
router = Router()


@router.message(Command("settings"))
async def cmd_settings(message: Message, state: FSMContext) -> None:
    if not await require_active_user(message):
        return
    await state.set_state(Settings.main_menu)
    await message.answer(msg.SETTINGS_MENU, reply_markup=kb.settings_menu_kb())


@router.callback_query(lambda c: c.data and c.data.startswith(f"{kb.CB_SETTINGS}:"))
async def cb_settings_axis(callback: CallbackQuery, state: FSMContext) -> None:
    axis = callback.data.split(":", 1)[1]

    if axis == "notifications":
        await callback.message.answer(msg.NOTIFICATIONS_STUB)
        await callback.answer()
        return

    await state.update_data(_editing_axis=axis)

    if axis == "budget":
        await state.set_state(Settings.edit_budget)
        await callback.message.answer(msg.ASK_BUDGET, reply_markup=kb.budget_kb())

    elif axis == "areas":
        loop = asyncio.get_running_loop()
        user = await loop.run_in_executor(None, _get_user, callback.from_user.id)
        current = user.areas if user else []
        await state.update_data(areas=list(current))
        await state.set_state(Settings.edit_areas)
        await callback.message.answer(msg.ASK_AREAS, reply_markup=kb.areas_kb(current))

    elif axis == "search_type":
        await state.set_state(Settings.edit_search_type)
        await callback.message.answer(msg.ASK_SEARCH_TYPE,
                                      reply_markup=kb.search_type_kb())

    elif axis == "gender_pref":
        await state.set_state(Settings.edit_gender_pref)
        await callback.message.answer(msg.ASK_GENDER_PREF,
                                      reply_markup=kb.gender_pref_kb())

    elif axis == "commute":
        await state.set_state(Settings.edit_commute_origin)
        await callback.message.answer(msg.ASK_COMMUTE_ORIGIN,
                                      reply_markup=kb.commute_skip_kb())

    elif axis == "dealbreakers":
        loop = asyncio.get_running_loop()
        user = await loop.run_in_executor(None, _get_user, callback.from_user.id)
        current = user.dealbreakers if user else []
        await state.update_data(dealbreakers=list(current))
        await state.set_state(Settings.edit_dealbreakers)
        await callback.message.answer(msg.ASK_DEALBREAKERS,
                                      reply_markup=kb.dealbreakers_kb(current))

    await callback.answer()


# ---------------------------------------------------------------------------
# Shared save helper
# ---------------------------------------------------------------------------

async def _finish_settings_edit(
    message: Message, state: FSMContext, fields: dict
) -> None:
    loop = asyncio.get_running_loop()
    tg_user_id = message.from_user.id
    pref_affecting = {
        "budget_min", "budget_max", "areas", "search_type",
        "commute_origin", "commute_origin_lat", "commute_origin_lng",
        "commute_max_minutes", "commute_mode", "dealbreakers",
    }

    def _save(fields: dict) -> None:
        from sqlalchemy import select
        from apps.shared.db import session_scope
        from apps.shared.models import User
        with session_scope() as s:
            user = s.execute(
                select(User).where(User.tg_user_id == tg_user_id)
            ).scalar_one_or_none()
            if user is None:
                return
            for k, v in fields.items():
                setattr(user, k, v)

    await loop.run_in_executor(None, _save, fields)

    needs_reembed = bool(set(fields) & pref_affecting)
    if needs_reembed:
        asyncio.create_task(_rebuild_embedding(tg_user_id))

    await state.clear()
    await message.answer(msg.SETTINGS_UPDATED, reply_markup=kb.settings_menu_kb())
    await state.set_state(Settings.main_menu)


async def _rebuild_embedding(tg_user_id: int) -> None:
    loop = asyncio.get_running_loop()
    from sqlalchemy import select
    from apps.shared.db import session_scope
    from apps.shared.models import User
    from apps.shared.enrichment.embed import build_user_pref_text
    from apps.shared.llm.gemini import GeminiClient

    def _load_user() -> User | None:
        with session_scope() as s:
            return s.execute(
                select(User).where(User.tg_user_id == tg_user_id)
            ).scalar_one_or_none()

    user = await loop.run_in_executor(None, _load_user)
    if user is None:
        return

    pref_text = build_user_pref_text(
        search_type=user.search_type,
        budget_min=user.budget_min,
        budget_max=user.budget_max,
        rooms=user.rooms,
        areas=user.areas or [],
        commute_origin=user.commute_origin,
        commute_max_minutes=user.commute_max_minutes,
        commute_mode=user.commute_mode,
        dealbreakers=user.dealbreakers or [],
        tradeoff_hint_text=user.tradeoff_hint_text,
        unacceptable_text=user.unacceptable_text,
    )
    try:
        gemini = GeminiClient()
        emb = await loop.run_in_executor(None, gemini.embed, pref_text)
    except Exception:
        log.warning("Embedding rebuild failed for user %s", tg_user_id)
        return

    def _update_emb(emb: list[float]) -> None:
        with session_scope() as s:
            u = s.execute(
                select(User).where(User.tg_user_id == tg_user_id)
            ).scalar_one_or_none()
            if u:
                u.preference_embedding = emb

    await loop.run_in_executor(None, _update_emb, emb)


# ---------------------------------------------------------------------------
# Per-axis edit completions
# ---------------------------------------------------------------------------

@router.callback_query(
    Settings.edit_budget,
    lambda c: c.data and c.data.startswith(f"{kb.CB_BUDGET}:")
)
async def cb_settings_budget(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    if parts[1] == "custom":
        await state.set_state(Settings.edit_budget_custom)
        await callback.message.answer(msg.ASK_BUDGET_CUSTOM_MAX)
        await callback.answer()
        return
    lo, hi = int(parts[1]), int(parts[2])
    await _finish_settings_edit(
        callback.message, state, {"budget_min": lo, "budget_max": hi}
    )
    await callback.answer()


@router.message(Settings.edit_budget_custom)
async def msg_settings_budget_custom(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    step = data.get("_settings_budget_step", "max")
    try:
        val = int(message.text.replace(" ", "").replace(",", ""))
    except ValueError:
        await message.answer("Введи число, например: 2500000")
        return
    if step == "max":
        await state.update_data(budget_max=val, _settings_budget_step="min")
        await message.answer(msg.ASK_BUDGET_CUSTOM_MIN)
    else:
        data2 = await state.get_data()
        await _finish_settings_edit(
            message, state, {"budget_min": val, "budget_max": data2["budget_max"]}
        )


@router.callback_query(
    Settings.edit_areas,
    lambda c: c.data and c.data.startswith(f"{kb.CB_AREA_TOGGLE}:")
)
async def cb_settings_area_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    area = callback.data.split(":", 1)[1]
    data = await state.get_data()
    selected = list(data.get("areas", []))
    if area in selected:
        selected.remove(area)
    else:
        selected.append(area)
    await state.update_data(areas=selected)
    await callback.message.edit_reply_markup(reply_markup=kb.areas_kb(selected))
    await callback.answer()


@router.callback_query(Settings.edit_areas, lambda c: c.data == kb.CB_AREA_DONE)
async def cb_settings_area_done(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    areas = data.get("areas", [])
    if not areas:
        await callback.answer("Выбери хотя бы один район", show_alert=True)
        return
    await _finish_settings_edit(callback.message, state, {"areas": areas})
    await callback.answer()


@router.callback_query(
    Settings.edit_search_type,
    lambda c: c.data and c.data.startswith(f"{kb.CB_SEARCH_TYPE}:")
)
async def cb_settings_search_type(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    fields: dict = {"search_type": value}
    if value in ("whole_apt_family", "whole_apt_solo"):
        fields["gender_pref"] = None
    await _finish_settings_edit(callback.message, state, fields)
    await callback.answer()


@router.callback_query(
    Settings.edit_gender_pref,
    lambda c: c.data and c.data.startswith(f"{kb.CB_GENDER_PREF}:")
)
async def cb_settings_gender_pref(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    await _finish_settings_edit(callback.message, state, {"gender_pref": value})
    await callback.answer()


@router.callback_query(
    Settings.edit_commute_origin,
    lambda c: c.data == kb.CB_COMMUTE_SKIP
)
async def cb_settings_commute_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await _finish_settings_edit(
        callback.message, state,
        {
            "commute_origin": None,
            "commute_origin_lat": None,
            "commute_origin_lng": None,
            "commute_max_minutes": None,
            "commute_mode": None,
        }
    )
    await callback.answer()


@router.message(Settings.edit_commute_origin)
async def msg_settings_commute_origin(message: Message, state: FSMContext) -> None:
    from apps.bot.handlers.onboarding import _geocode_async
    result = await _geocode_async(message.text.strip())
    if result.lat is None:
        await message.answer(msg.GEOCODE_FAILED, reply_markup=kb.commute_skip_kb())
        return
    await state.update_data(
        commute_origin=message.text.strip(),
        commute_origin_lat=result.lat,
        commute_origin_lng=result.lng,
    )
    await state.set_state(Settings.edit_commute_minutes)
    await message.answer(msg.ASK_COMMUTE_MINUTES, reply_markup=kb.commute_minutes_kb())


@router.callback_query(
    Settings.edit_commute_minutes,
    lambda c: c.data and c.data.startswith(f"{kb.CB_COMMUTE_MINUTES}:")
)
async def cb_settings_commute_minutes(
    callback: CallbackQuery, state: FSMContext
) -> None:
    val = int(callback.data.split(":")[1])
    await state.update_data(commute_max_minutes=val)
    await state.set_state(Settings.edit_commute_mode)
    await callback.message.answer(msg.ASK_COMMUTE_MODE,
                                  reply_markup=kb.commute_mode_kb())
    await callback.answer()


@router.callback_query(
    Settings.edit_commute_mode,
    lambda c: c.data and c.data.startswith(f"{kb.CB_COMMUTE_MODE}:")
)
async def cb_settings_commute_mode(callback: CallbackQuery, state: FSMContext) -> None:
    mode = callback.data.split(":", 1)[1]
    data = await state.get_data()
    await _finish_settings_edit(
        callback.message, state,
        {
            "commute_origin": data.get("commute_origin"),
            "commute_origin_lat": data.get("commute_origin_lat"),
            "commute_origin_lng": data.get("commute_origin_lng"),
            "commute_max_minutes": data.get("commute_max_minutes"),
            "commute_mode": mode,
        }
    )
    await callback.answer()


@router.callback_query(
    Settings.edit_dealbreakers,
    lambda c: c.data and c.data.startswith(f"{kb.CB_DB_TOGGLE}:")
)
async def cb_settings_db_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":", 1)[1]
    data = await state.get_data()
    selected = list(data.get("dealbreakers", []))
    if key in selected:
        selected.remove(key)
    else:
        selected.append(key)
    await state.update_data(dealbreakers=selected)
    await callback.message.edit_reply_markup(reply_markup=kb.dealbreakers_kb(selected))
    await callback.answer()


@router.callback_query(Settings.edit_dealbreakers, lambda c: c.data == kb.CB_DB_DONE)
async def cb_settings_db_done(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await _finish_settings_edit(
        callback.message, state,
        {"dealbreakers": data.get("dealbreakers", [])}
    )
    await callback.answer()
