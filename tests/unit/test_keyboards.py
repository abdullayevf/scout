from apps.bot.keyboards import (
    start_kb, search_type_kb, areas_kb, dealbreakers_kb,
    axis_priority_kb, confirm_kb, AREAS,
)
from aiogram.types import InlineKeyboardMarkup


def test_start_kb_returns_markup():
    kb = start_kb()
    assert isinstance(kb, InlineKeyboardMarkup)
    assert kb.inline_keyboard[0][0].callback_data == "start"


def test_areas_kb_toggles_checkmark():
    kb_none = areas_kb([])
    kb_sel = areas_kb(["Yunusabad"])
    texts_none = [btn.text for row in kb_none.inline_keyboard for btn in row]
    texts_sel = [btn.text for row in kb_sel.inline_keyboard for btn in row]
    assert any("Yunusabad" == t for t in texts_none)
    assert any("✅ Yunusabad" == t for t in texts_sel)


def test_dealbreakers_kb_toggles():
    kb = dealbreakers_kb(["no_first_floor"])
    flat = [btn.text for row in kb.inline_keyboard for btn in row]
    assert any("✅" in t and "этаж" in t.lower() for t in flat)


def test_axis_priority_kb_contains_must_nice():
    kb = axis_priority_kb("budget")
    flat = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "axis:must:budget" in flat
    assert "axis:nice:budget" in flat


def test_confirm_kb_data():
    kb = confirm_kb(yes_data="del_yes", no_data="del_no",
                    yes_label="Да, удалить", no_label="Отмена")
    row = kb.inline_keyboard[0]
    assert row[0].callback_data == "del_yes"
    assert row[1].callback_data == "del_no"
