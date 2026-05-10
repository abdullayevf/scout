from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

CB_START = "start"
CB_SEARCH_TYPE = "st"
CB_GENDER_PREF = "gp"
CB_BUDGET = "budget"
CB_ROOMS = "rooms"
CB_AREA_TOGGLE = "area_toggle"
CB_AREA_CUSTOM = "area_custom"
CB_AREA_DONE = "area_done"
CB_MOVE_IN = "move_in"
CB_COMMUTE_SKIP = "commute_skip"
CB_COMMUTE_MINUTES = "commute_min"
CB_COMMUTE_MODE = "commute_mode"
CB_DB_TOGGLE = "db_toggle"
CB_DB_DONE = "db_done"
CB_AGENT_FILTER = "af"
CB_AXIS = "axis"
CB_FREE_TEXT_WALL = "ftw"
CB_FREE_TEXT_SKIP = "fts"
CB_DELETE_YES = "del_yes"
CB_DELETE_NO = "del_no"
CB_REONBOARD_YES = "reonboard_yes"
CB_REONBOARD_NO = "reonboard_no"
CB_SETTINGS = "settings"

AREAS = [
    "Bektemir", "Chilanzar", "Mirobod", "Mirzo Ulugbek",
    "Sergeli", "Shaykhantakhur", "Uchtepa", "Yakkasaray",
    "Yashnobod", "Yunusabad", "Almazar", "Yangihayot",
]

DEALBREAKERS = [
    ("no_shared_bath", "🚿 Без общего санузла"),
    ("must_parking", "🚗 Нужна парковка"),
    ("no_first_floor", "⬆️ Не первый этаж"),
    ("no_agent_fee", "💸 Без комиссии агента"),
    ("must_furnished", "🛋️ Только с мебелью"),
    ("no_basement", "🏢 Не цоколь"),
]

AXIS_LABELS = {
    "budget": "💰 Бюджет",
    "area": "📍 Район",
    "commute": "🚇 Маршрут",
    "rooms": "🛏️ Количество комнат",
    "furnishing": "🛋️ Мебель",
}

BUDGET_PRESETS = [
    ("до 1 500 000", 0, 1_500_000),
    ("1.5 — 2.5 млн", 1_500_000, 2_500_000),
    ("2.5 — 4 млн", 2_500_000, 4_000_000),
    ("4 — 7 млн", 4_000_000, 7_000_000),
    ("от 7 млн", 7_000_000, 999_999_999),
]


def start_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Начать ▶️", callback_data=CB_START)
    ]])


def search_type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Квартира для семьи",
                              callback_data=f"{CB_SEARCH_TYPE}:whole_apt_family")],
        [InlineKeyboardButton(text="🏠 Квартира (1–2 чел.)",
                              callback_data=f"{CB_SEARCH_TYPE}:whole_apt_solo")],
        [InlineKeyboardButton(text="🛏️ Комната в квартире",
                              callback_data=f"{CB_SEARCH_TYPE}:shared_room")],
        [InlineKeyboardButton(text="🤝 Ищу соседа",
                              callback_data=f"{CB_SEARCH_TYPE}:looking_for_roommate")],
    ])


def gender_pref_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👫 Любой",
                              callback_data=f"{CB_GENDER_PREF}:any")],
        [InlineKeyboardButton(text="👨 Только мужчины",
                              callback_data=f"{CB_GENDER_PREF}:male")],
        [InlineKeyboardButton(text="👩 Только женщины",
                              callback_data=f"{CB_GENDER_PREF}:female")],
    ])


def budget_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label,
                              callback_data=f"{CB_BUDGET}:{lo}:{hi}")]
        for label, lo, hi in BUDGET_PRESETS
    ]
    rows.append([InlineKeyboardButton(text="✏️ Ввести свой",
                                      callback_data=f"{CB_BUDGET}:custom")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def rooms_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=label, callback_data=f"{CB_ROOMS}:{val}")
        for label, val in [("Любое", 0), ("1", 1), ("2", 2), ("3", 3), ("4+", 4)]
    ]])


def areas_kb(selected: list[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for area in AREAS:
        label = f"✅ {area}" if area in selected else area
        builder.button(text=label, callback_data=f"{CB_AREA_TOGGLE}:{area}")
    builder.adjust(2)
    builder.row(
        InlineKeyboardButton(text="➕ Свой район", callback_data=CB_AREA_CUSTOM),
        InlineKeyboardButton(text="Готово ✓", callback_data=CB_AREA_DONE),
    )
    return builder.as_markup()


def move_in_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Сейчас", callback_data=f"{CB_MOVE_IN}:now"),
         InlineKeyboardButton(text="Через 2 недели", callback_data=f"{CB_MOVE_IN}:2_weeks")],
        [InlineKeyboardButton(text="Через месяц", callback_data=f"{CB_MOVE_IN}:1_month"),
         InlineKeyboardButton(text="Гибко", callback_data=f"{CB_MOVE_IN}:flexible")],
    ])


def commute_skip_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Пропустить", callback_data=CB_COMMUTE_SKIP)
    ]])


def commute_minutes_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"{m} мин",
                             callback_data=f"{CB_COMMUTE_MINUTES}:{m}")
        for m in [15, 20, 30, 45, 60]
    ]])


def commute_mode_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🚶 Пешком",
                             callback_data=f"{CB_COMMUTE_MODE}:walk"),
        InlineKeyboardButton(text="🚗 Машина",
                             callback_data=f"{CB_COMMUTE_MODE}:car"),
        InlineKeyboardButton(text="🚌 Общественный",
                             callback_data=f"{CB_COMMUTE_MODE}:public"),
    ]])


def dealbreakers_kb(selected: list[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key, label in DEALBREAKERS:
        text = f"✅ {label}" if key in selected else label
        builder.button(text=text, callback_data=f"{CB_DB_TOGGLE}:{key}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="Готово ✓", callback_data=CB_DB_DONE))
    return builder.as_markup()


def agent_filter_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="👤 Только хозяин",
                             callback_data=f"{CB_AGENT_FILTER}:owner_only"),
        InlineKeyboardButton(text="Агенты тоже ок",
                             callback_data=f"{CB_AGENT_FILTER}:agents_ok"),
    ]])


def axis_priority_kb(axis_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔒 Обязательно",
                             callback_data=f"{CB_AXIS}:must:{axis_key}"),
        InlineKeyboardButton(text="✨ Желательно",
                             callback_data=f"{CB_AXIS}:nice:{axis_key}"),
    ]])


def free_text_wall_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Да, уточню",
                             callback_data=f"{CB_FREE_TEXT_WALL}:yes"),
        InlineKeyboardButton(text="Пропустить",
                             callback_data=f"{CB_FREE_TEXT_WALL}:skip"),
    ]])


def free_text_skip_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Пропустить", callback_data=CB_FREE_TEXT_SKIP)
    ]])


def confirm_kb(
    *,
    yes_data: str,
    no_data: str,
    yes_label: str = "Да",
    no_label: str = "Отмена",
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=yes_label, callback_data=yes_data),
        InlineKeyboardButton(text=no_label, callback_data=no_data),
    ]])


def settings_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Бюджет",
                              callback_data=f"{CB_SETTINGS}:budget"),
         InlineKeyboardButton(text="📍 Районы",
                              callback_data=f"{CB_SETTINGS}:areas")],
        [InlineKeyboardButton(text="🏠 Тип поиска",
                              callback_data=f"{CB_SETTINGS}:search_type"),
         InlineKeyboardButton(text="👤 Пол",
                              callback_data=f"{CB_SETTINGS}:gender_pref")],
        [InlineKeyboardButton(text="🚇 Маршрут",
                              callback_data=f"{CB_SETTINGS}:commute"),
         InlineKeyboardButton(text="🚫 Стоп-факторы",
                              callback_data=f"{CB_SETTINGS}:dealbreakers")],
        [InlineKeyboardButton(text="🔔 Уведомления",
                              callback_data=f"{CB_SETTINGS}:notifications")],
    ])
