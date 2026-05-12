from apps.bot.keyboards import chase_48h_kb, chase_5d_kb, rented_pause_kb, weekly_checkin_kb


def test_chase_48h_kb_has_yes_and_no():
    kb = chase_48h_kb(7)
    flat = [btn for row in kb.inline_keyboard for btn in row]
    datas = {b.callback_data for b in flat}
    assert "chase48y:7" in datas
    assert "chase48n:7" in datas


def test_chase_5d_kb_has_yes_and_no():
    kb = chase_5d_kb(8)
    flat = [btn for row in kb.inline_keyboard for btn in row]
    datas = {b.callback_data for b in flat}
    assert "chase5y:8" in datas
    assert "chase5n:8" in datas


def test_weekly_checkin_kb_has_three_options():
    kb = weekly_checkin_kb()
    flat = [btn for row in kb.inline_keyboard for btn in row]
    datas = {b.callback_data for b in flat}
    assert "wcheckin:searching" in datas
    assert "wcheckin:found" in datas
    assert "wcheckin:quit" in datas


def test_rented_pause_kb_has_pause_and_continue():
    kb = rented_pause_kb()
    flat = [btn for row in kb.inline_keyboard for btn in row]
    datas = {b.callback_data for b in flat}
    assert "rented:pause" in datas
    assert "rented:continue" in datas
