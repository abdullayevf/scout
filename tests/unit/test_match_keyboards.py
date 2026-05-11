from aiogram.types import InlineKeyboardMarkup
from apps.bot.keyboards import dislike_reasons_kb, match_actions_kb

def test_match_actions_kb_three_buttons():
    kb = match_actions_kb(42)
    assert isinstance(kb, InlineKeyboardMarkup)
    row = kb.inline_keyboard[0]
    assert len(row) == 3
    cbs = [b.callback_data for b in row]
    assert "like:42" in cbs
    assert "dislike:42" in cbs
    assert "contact:42" in cbs

def test_dislike_reasons_kb_four_options():
    kb = dislike_reasons_kb(99)
    flat = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "dislike_reason:expensive:99" in flat
    assert "dislike_reason:area:99" in flat
    assert "dislike_reason:fishy:99" in flat
    assert "dislike_reason:seen:99" in flat
