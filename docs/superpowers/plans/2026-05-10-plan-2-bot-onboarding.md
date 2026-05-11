# Scout Plan 2: Bot Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the aiogram Telegram bot with webhook delivery, full structured + free-text onboarding FSM, /settings per-axis edit, and /pause /resume /reonboard /delete commands — producing a working bot that stores a complete user profile in Postgres.

**Architecture:** Standalone `bot` docker-compose service running an aiohttp webhook server on port 8080; nginx terminates TLS and proxies `/bot/webhook` to it. All bot state (mid-onboarding progress) stored in Redis via aiogram `RedisStorage`. Gemini calls (keyword extraction, embedding) and DB writes are synchronous functions called via `asyncio.run_in_executor` from async handlers.

**Tech stack:** aiogram 3.13+ (already in pyproject.toml), aiohttp (aiogram dependency, already installed), redis 5.2+ (already in pyproject.toml), SQLAlchemy 2, Alembic, GeminiClient (existing), geocode() (existing sync function in apps/shared/geo/yandex.py)

---

## File map

| File | Action | Purpose |
|---|---|---|
| `apps/shared/enums.py` | modify | add `UserState` StrEnum |
| `apps/shared/models.py` | modify | add `User`, `Event` models |
| `alembic/versions/<hash>_add_users_events.py` | create | migration |
| `apps/shared/config.py` | modify | add telegram vars |
| `apps/shared/enrichment/embed.py` | modify | add `build_user_pref_text()` |
| `apps/bot/__init__.py` | create | empty |
| `apps/bot/states.py` | create | `Onboarding` + `Settings` FSM states |
| `apps/bot/messages.py` | create | all Russian message text constants |
| `apps/bot/keyboards.py` | create | all `InlineKeyboardMarkup` builders |
| `apps/bot/handlers/__init__.py` | create | empty |
| `apps/bot/handlers/commands.py` | create | guard middleware, /help /pause /resume /delete /reonboard |
| `apps/bot/handlers/onboarding.py` | create | /start + 17-state onboarding FSM |
| `apps/bot/handlers/settings.py` | create | /settings per-axis edit |
| `apps/bot/main.py` | create | Dispatcher + aiohttp webhook server |
| `docker-compose.yml` | modify | add `bot` + `nginx` services |
| `infra/nginx.conf` | create | TLS termination + webhook proxy |
| `tests/unit/test_user_model.py` | create | User/Event DB tests |
| `tests/unit/test_onboarding_flow.py` | create | FSM state transition tests |
| `tests/unit/test_commands.py` | create | guard, pause/resume, delete tests |

---

## Task 1: UserState enum + User and Event SQLAlchemy models

**Files:**
- Modify: `apps/shared/enums.py`
- Modify: `apps/shared/models.py`
- Create: `tests/unit/test_user_model.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_user_model.py
import pytest
from sqlalchemy import inspect, text
from apps.shared.models import Base, User, Event
from apps.shared.enums import UserState


def test_user_table_exists(engine):
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    assert "users" in insp.get_table_names()


def test_event_table_exists(engine):
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    assert "events" in insp.get_table_names()


def test_user_create_minimal(db_session):
    Base.metadata.create_all(db_session.bind)
    u = User(tg_user_id=111, state=UserState.ONBOARDING)
    db_session.add(u)
    db_session.flush()
    assert u.id is not None
    assert u.state == "onboarding"


def test_user_tg_user_id_unique(db_session):
    from sqlalchemy.exc import IntegrityError
    Base.metadata.create_all(db_session.bind)
    db_session.add(User(tg_user_id=222, state=UserState.ONBOARDING))
    db_session.flush()
    db_session.add(User(tg_user_id=222, state=UserState.ONBOARDING))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_event_create(db_session):
    Base.metadata.create_all(db_session.bind)
    e = Event(kind="onboarding_started", user_id=333)
    db_session.add(e)
    db_session.flush()
    assert e.id is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/maurilar/petties/apt
uv run pytest tests/unit/test_user_model.py -v
```

Expected: FAIL — `cannot import name 'User' from 'apps.shared.models'`

- [ ] **Step 3: Add `UserState` to enums**

Append to `apps/shared/enums.py`:

```python
class UserState(StrEnum):
    ONBOARDING = "onboarding"
    ACTIVE = "active"
    PAUSED = "paused"
    SUCCESS = "success"
    DELETED = "deleted"
```

- [ ] **Step 4: Add `User` and `Event` models to `apps/shared/models.py`**

Add the following imports at the top (merge with existing imports):

```python
from sqlalchemy import (
    ARRAY, BigInteger, Boolean, DateTime, Float, Index, Integer,
    String, Text, UniqueConstraint, func,
)
```

(These are already imported — no change needed. Just confirm `JSONB` is also imported from `sqlalchemy.dialects.postgresql`.)

Append to the bottom of `apps/shared/models.py`:

```python
from apps.shared.enums import UserState  # add to existing enums import line


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    tg_username: Mapped[str | None] = mapped_column(Text)

    search_type: Mapped[str | None] = mapped_column(String(32))
    gender_pref: Mapped[str | None] = mapped_column(String(8))
    agent_filter: Mapped[str | None] = mapped_column(String(16))
    budget_min: Mapped[int | None] = mapped_column(BigInteger)
    budget_max: Mapped[int | None] = mapped_column(BigInteger)
    rooms: Mapped[int | None] = mapped_column(Integer)
    areas: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    move_in_window: Mapped[str | None] = mapped_column(String(16))

    commute_origin: Mapped[str | None] = mapped_column(Text)
    commute_origin_lat: Mapped[float | None] = mapped_column(Float)
    commute_origin_lng: Mapped[float | None] = mapped_column(Float)
    commute_max_minutes: Mapped[int | None] = mapped_column(Integer)
    commute_mode: Mapped[str | None] = mapped_column(String(8))

    dealbreakers: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    dealbreaker_keywords: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    axis_priority: Mapped[dict] = mapped_column(JSONB, default=dict)

    tradeoff_hint_text: Mapped[str | None] = mapped_column(Text)
    unacceptable_text: Mapped[str | None] = mapped_column(Text)
    instant_reject_text: Mapped[str | None] = mapped_column(Text)
    preference_embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dim)
    )

    negative_area_mask: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    distrust_set: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    seen_set: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), default=list)
    top_1pct_threshold: Mapped[float | None] = mapped_column(Float)

    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default=UserState.ONBOARDING, index=True
    )
    paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    listing_id: Mapped[int | None] = mapped_column(BigInteger)
    match_id: Mapped[int | None] = mapped_column(BigInteger)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
```

Also update the existing `enums` import line in `models.py` to include `UserState`:

```python
from apps.shared.enums import (  # noqa: F401
    BathroomType,
    GenderConstraint,
    ListingState,
    OlxCategory,
    PosterRole,
    SearchType,
    UserState,
)
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_user_model.py -v
```

Expected: PASS (all 5 tests)

- [ ] **Step 6: Commit**

```bash
git add apps/shared/enums.py apps/shared/models.py tests/unit/test_user_model.py
git commit -m "feat: add User and Event models with UserState enum"
```

---

## Task 2: Alembic migration for users + events

**Files:**
- Create: `alembic/versions/<hash>_add_users_events.py`

- [ ] **Step 1: Generate the migration**

```bash
cd /home/maurilar/petties/apt
uv run alembic revision --autogenerate -m "add_users_events"
```

Expected: new file created in `alembic/versions/` with `op.create_table('users', ...)` and `op.create_table('events', ...)`.

- [ ] **Step 2: Inspect the generated file**

Open the generated file. Verify it contains:
- `op.create_table('users', ...)` with all columns
- `op.create_index(...)` for `tg_user_id`, `state`
- `op.create_table('events', ...)` with all columns
- `upgrade()` and `downgrade()` functions

If autogenerate missed the `vector` column type, add manually in the migration:

```python
from pgvector.sqlalchemy import Vector
# in upgrade():
sa.Column('preference_embedding', Vector(3072), nullable=True),
```

- [ ] **Step 3: Apply the migration against the dev DB**

```bash
uv run alembic upgrade head
```

Expected: `Running upgrade <prev> -> <new>, add_users_events`

- [ ] **Step 4: Verify tables exist**

```bash
docker compose exec postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -c "\dt"
```

Expected: `users` and `events` appear in the table list.

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/
git commit -m "feat: migration add users and events tables"
```

---

## Task 3: Telegram config vars + user pref embedding text builder

**Files:**
- Modify: `apps/shared/config.py`
- Modify: `apps/shared/enrichment/embed.py`
- Modify: `tests/unit/test_config.py` (add one assertion)

- [ ] **Step 1: Write a failing test for config**

Add to `tests/unit/test_config.py`:

```python
def test_telegram_fields_present():
    from apps.shared.config import Settings
    fields = Settings.model_fields
    assert "telegram_bot_token" in fields
    assert "telegram_webhook_url" in fields
    assert "telegram_webhook_secret" in fields
```

Run:

```bash
uv run pytest tests/unit/test_config.py::test_telegram_fields_present -v
```

Expected: FAIL

- [ ] **Step 2: Add telegram vars to Settings**

In `apps/shared/config.py`, add to the `Settings` class (after `enrichment_workers`):

```python
    telegram_bot_token: str = ""
    telegram_webhook_url: str = ""
    telegram_webhook_secret: str = ""
```

- [ ] **Step 3: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_config.py::test_telegram_fields_present -v
```

Expected: PASS

- [ ] **Step 4: Write a failing test for pref text builder**

Add to `tests/unit/test_embed.py`:

```python
def test_build_user_pref_text_includes_search_type():
    from apps.shared.enrichment.embed import build_user_pref_text
    text = build_user_pref_text(
        search_type="whole_apt_solo",
        budget_min=1_000_000,
        budget_max=3_000_000,
        rooms=2,
        areas=["Yunusabad", "Chilanzar"],
        commute_origin="TUIT university",
        commute_max_minutes=30,
        commute_mode="public",
        dealbreakers=["no_first_floor"],
        tradeoff_hint_text=None,
        unacceptable_text=None,
    )
    assert "whole_apt_solo" in text
    assert "Yunusabad" in text
    assert "1000000" in text
```

Run:

```bash
uv run pytest tests/unit/test_embed.py::test_build_user_pref_text_includes_search_type -v
```

Expected: FAIL — `cannot import name 'build_user_pref_text'`

- [ ] **Step 5: Add `build_user_pref_text` to embed.py**

Append to `apps/shared/enrichment/embed.py`:

```python
def build_user_pref_text(
    *,
    search_type: str | None,
    budget_min: int | None,
    budget_max: int | None,
    rooms: int | None,
    areas: list[str],
    commute_origin: str | None,
    commute_max_minutes: int | None,
    commute_mode: str | None,
    dealbreakers: list[str],
    tradeoff_hint_text: str | None,
    unacceptable_text: str | None,
) -> str:
    parts = []
    if search_type:
        parts.append(f"search_type={search_type}")
    if budget_min is not None:
        parts.append(f"budget_min={budget_min}")
    if budget_max is not None:
        parts.append(f"budget_max={budget_max}")
    if rooms is not None:
        parts.append(f"rooms={rooms}")
    if areas:
        parts.append("areas=" + ",".join(areas))
    if commute_origin:
        parts.append(f"commute_from={commute_origin}")
    if commute_max_minutes is not None:
        parts.append(f"commute_max={commute_max_minutes}min")
    if commute_mode:
        parts.append(f"commute_mode={commute_mode}")
    if dealbreakers:
        parts.append("dealbreakers=" + ",".join(dealbreakers))
    if tradeoff_hint_text:
        parts.append(tradeoff_hint_text)
    if unacceptable_text:
        parts.append(unacceptable_text)
    return "\n".join(parts)
```

- [ ] **Step 6: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_embed.py::test_build_user_pref_text_includes_search_type -v
```

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apps/shared/config.py apps/shared/enrichment/embed.py tests/unit/test_config.py tests/unit/test_embed.py
git commit -m "feat: telegram config vars, user pref embedding text builder"
```

---

## Task 4: Bot states + message constants

**Files:**
- Create: `apps/bot/__init__.py`
- Create: `apps/bot/states.py`
- Create: `apps/bot/messages.py`
- Create: `apps/bot/handlers/__init__.py`

No tests for these (pure constants — tested implicitly by handler tests).

- [ ] **Step 1: Create empty package files**

```bash
touch /home/maurilar/petties/apt/apps/bot/__init__.py
mkdir -p /home/maurilar/petties/apt/apps/bot/handlers
touch /home/maurilar/petties/apt/apps/bot/handlers/__init__.py
```

- [ ] **Step 2: Create `apps/bot/states.py`**

```python
from aiogram.fsm.state import State, StatesGroup


class Onboarding(StatesGroup):
    search_type = State()
    gender_pref = State()
    budget = State()
    budget_custom = State()
    rooms = State()
    areas = State()
    move_in = State()
    commute_origin = State()
    commute_minutes = State()
    commute_mode = State()
    dealbreakers = State()
    agent_filter = State()
    axis_priority = State()
    free_text_wall = State()
    free_text_1 = State()
    free_text_2 = State()
    free_text_3 = State()


class Settings(StatesGroup):
    main_menu = State()
    edit_budget = State()
    edit_budget_custom = State()
    edit_areas = State()
    edit_search_type = State()
    edit_gender_pref = State()
    edit_commute_origin = State()
    edit_commute_minutes = State()
    edit_commute_mode = State()
    edit_dealbreakers = State()
    edit_agent_filter = State()
```

- [ ] **Step 3: Create `apps/bot/messages.py`**

```python
WELCOME = (
    "👋 Привет! Я Scout — помогу найти квартиру в Ташкенте быстрее.\n\n"
    "Что я делаю:\n"
    "• Каждые 5 минут проверяю новые объявления на OLX\n"
    "• Убираю дубли, старые объявления и подозрительные посты\n"
    "• Раз в день в 09:00 присылаю 8 лучших вариантов под твои критерии\n"
    "• Сразу присылаю горячие топ-варианты (макс. 3/день)\n"
    "• Учусь на твоих 👍 и 👎 — со временем рекомендации становятся точнее\n\n"
    "Готов начать? Займёт ~2 минуты."
)

HELP = (
    "Команды:\n"
    "/settings — изменить критерии поиска\n"
    "/reonboard — пройти опрос заново\n"
    "/pause — поставить поиск на паузу\n"
    "/resume — возобновить поиск\n"
    "/delete — удалить все мои данные\n"
    "/help — это сообщение\n\n"
    "Вопросы и предложения: @golibabdullayev"
)

ASK_SEARCH_TYPE = "Что ищешь?"
ASK_GENDER_PREF = "Какой пол предпочитаешь для совместного проживания?"
ASK_BUDGET = "Какой бюджет на аренду в месяц (в UZS)?"
ASK_BUDGET_CUSTOM_MAX = "Введи максимальный бюджет в UZS (например: 2500000):"
ASK_BUDGET_CUSTOM_MIN = "Введи минимальный бюджет в UZS (или 0 если нет минимума):"
ASK_ROOMS = "Сколько комнат?"
ASK_AREAS = (
    "Какие районы рассматриваешь? Можно выбрать несколько.\n"
    "Нажми [Готово ✓] когда выберешь."
)
ASK_CUSTOM_AREA = (
    "Введи название района или ориентира\n"
    "(например: «Чиланзар-19» или «рядом с TUIT»):"
)
ASK_MOVE_IN = "Когда планируешь въехать?"
ASK_COMMUTE_ORIGIN = (
    "Откуда обычно добираешься на работу/учёбу? Введи адрес или ориентир.\n"
    "Это нужно, чтобы я учитывал время в пути."
)
ASK_COMMUTE_MINUTES = "Сколько минут максимум готов добираться?"
ASK_COMMUTE_MODE = "На чём добираешься?"
ASK_DEALBREAKERS = (
    "Есть ли стоп-факторы? Можно выбрать несколько.\n"
    "Нажми [Готово ✓] когда выберешь."
)
ASK_AGENT_FILTER = "Рассматриваешь ли объявления от агентов?"
ASK_AXIS_PRIORITY = "Насколько важен критерий «{axis}»?"
FREE_TEXT_WALL = (
    "✅ Основное готово! Хочешь уточнить детали? Помогает подобрать точнее. "
    "(3 вопроса, ~1 мин)"
)
FREE_TEXT_1 = "(1/3) Что важнее: уложиться в бюджет или сократить время в пути?"
FREE_TEXT_2 = "(2/3) Что делало предыдущие варианты неприемлемыми?"
FREE_TEXT_3 = "(3/3) Что для тебя — мгновенный отказ от варианта?"
BUILDING_PROFILE = "⏳ Настраиваю профиль..."
ONBOARDING_DONE = (
    "✅ Всё настроено! Буду присылать подборку каждый день в 09:00.\n\n"
    "/settings — изменить критерии\n"
    "/pause — поставить на паузу\n"
    "/help — все команды"
)

PAUSE_OK = "Поиск на паузе. /resume чтобы возобновить."
PAUSE_ALREADY = "Уже на паузе."
RESUME_OK = "Поиск возобновлён ✅"
RESUME_NOT_PAUSED = "Поиск уже активен."
DELETE_CONFIRM = "⚠️ Удалить все данные? Это необратимо."
DELETE_DONE = "Готово. Все данные удалены."
DELETE_CANCELLED = "Отмена."
REONBOARD_CONFIRM = "Начнём заново? Все текущие настройки будут заменены."
REONBOARD_CANCELLED = "Отмена."
NOT_ONBOARDED = "Сначала пройди онбординг — /start"
NOTIFICATIONS_STUB = (
    "Настройки уведомлений появятся после запуска подборок (план 3)."
)
SETTINGS_MENU = "Что хочешь изменить?"
SETTINGS_UPDATED = "✅ Обновлено."
GEOCODE_FAILED = (
    "Не удалось определить адрес. Попробуй написать точнее или нажми «Пропустить»."
)
```

- [ ] **Step 4: Commit**

```bash
git add apps/bot/
git commit -m "feat: bot package skeleton, FSM states, message constants"
```

---

## Task 5: Keyboard builders

**Files:**
- Create: `apps/bot/keyboards.py`

- [ ] **Step 1: Write a failing test**

Create `tests/unit/test_keyboards.py`:

```python
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
```

Run:

```bash
uv run pytest tests/unit/test_keyboards.py -v
```

Expected: FAIL — `No module named 'apps.bot.keyboards'`

- [ ] **Step 2: Create `apps/bot/keyboards.py`**

```python
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
```

- [ ] **Step 3: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_keyboards.py -v
```

Expected: PASS (all 5 tests)

- [ ] **Step 4: Commit**

```bash
git add apps/bot/keyboards.py tests/unit/test_keyboards.py
git commit -m "feat: inline keyboard builders"
```

---

## Task 6: Guard middleware + /help, /pause, /resume

**Files:**
- Create: `apps/bot/handlers/commands.py`
- Create: `tests/unit/test_commands.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_commands.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from apps.shared.enums import UserState


def make_message(user_id: int = 123, text: str = "/help") -> MagicMock:
    msg = AsyncMock()
    msg.text = text
    msg.from_user = MagicMock(id=user_id, username="tester")
    msg.answer = AsyncMock()
    return msg


async def make_ctx(storage: MemoryStorage, user_id: int = 123) -> FSMContext:
    key = StorageKey(bot_id=1, user_id=user_id, chat_id=user_id)
    return FSMContext(storage=storage, key=key)


def make_user_row(state: str = UserState.ACTIVE):
    u = MagicMock()
    u.state = state
    u.id = 1
    return u


@pytest.mark.asyncio
async def test_help_always_works():
    from apps.bot.handlers.commands import cmd_help
    msg = make_message()
    await cmd_help(msg)
    msg.answer.assert_called_once()
    text = msg.answer.call_args[0][0]
    assert "/settings" in text


@pytest.mark.asyncio
async def test_pause_sets_state_paused():
    from apps.bot.handlers.commands import cmd_pause
    msg = make_message()
    user = make_user_row(UserState.ACTIVE)
    with patch("apps.bot.handlers.commands._get_user", return_value=user), \
         patch("apps.bot.handlers.commands._save_user") as save_mock:
        await cmd_pause(msg)
        assert user.state == UserState.PAUSED
        save_mock.assert_called_once_with(user)
        msg.answer.assert_called_once()


@pytest.mark.asyncio
async def test_pause_already_paused():
    from apps.bot.handlers.commands import cmd_pause
    msg = make_message()
    user = make_user_row(UserState.PAUSED)
    with patch("apps.bot.handlers.commands._get_user", return_value=user):
        await cmd_pause(msg)
        text = msg.answer.call_args[0][0]
        assert "паузе" in text.lower()


@pytest.mark.asyncio
async def test_resume_sets_state_active():
    from apps.bot.handlers.commands import cmd_resume
    msg = make_message()
    user = make_user_row(UserState.PAUSED)
    with patch("apps.bot.handlers.commands._get_user", return_value=user), \
         patch("apps.bot.handlers.commands._save_user") as save_mock:
        await cmd_resume(msg)
        assert user.state == UserState.ACTIVE
        save_mock.assert_called_once()


@pytest.mark.asyncio
async def test_guard_blocks_unknown_user():
    from apps.bot.handlers.commands import require_active_user
    msg = make_message()
    with patch("apps.bot.handlers.commands._get_user", return_value=None):
        result = await require_active_user(msg)
        assert result is False
        msg.answer.assert_called_once()
        assert "/start" in msg.answer.call_args[0][0]
```

Run:

```bash
uv run pytest tests/unit/test_commands.py -v
```

Expected: FAIL — module not found

- [ ] **Step 2: Create `apps/bot/handlers/commands.py`**

```python
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from apps.bot import keyboards as kb
from apps.bot import messages as msg
from apps.shared.db import session_scope
from apps.shared.enums import UserState
from apps.shared.models import Event, User

log = logging.getLogger(__name__)
router = Router()


# ---------------------------------------------------------------------------
# Internal helpers (sync, called via run_in_executor from async handlers)
# ---------------------------------------------------------------------------

def _get_user(tg_user_id: int) -> User | None:
    with session_scope() as s:
        return s.execute(
            select(User).where(User.tg_user_id == tg_user_id)
        ).scalar_one_or_none()


def _save_user(user: User) -> None:
    with session_scope() as s:
        s.merge(user)


def _write_event(kind: str, user_id: int | None) -> None:
    with session_scope() as s:
        s.add(Event(kind=kind, user_id=user_id))


# ---------------------------------------------------------------------------
# Guard helper — returns False and replies if user not found or deleted
# ---------------------------------------------------------------------------

async def require_active_user(message: Message) -> bool:
    loop = asyncio.get_event_loop()
    user = await loop.run_in_executor(None, _get_user, message.from_user.id)
    if user is None or user.state == UserState.DELETED:
        await message.answer(msg.NOT_ONBOARDED)
        return False
    return True


# ---------------------------------------------------------------------------
# /help — always works regardless of user state
# ---------------------------------------------------------------------------

@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(msg.HELP)


# ---------------------------------------------------------------------------
# /pause
# ---------------------------------------------------------------------------

@router.message(Command("pause"))
async def cmd_pause(message: Message) -> None:
    loop = asyncio.get_event_loop()
    user = await loop.run_in_executor(None, _get_user, message.from_user.id)
    if user is None or user.state == UserState.DELETED:
        await message.answer(msg.NOT_ONBOARDED)
        return
    if user.state == UserState.PAUSED:
        await message.answer(msg.PAUSE_ALREADY)
        return
    user.state = UserState.PAUSED
    user.paused_until = None
    await loop.run_in_executor(None, _save_user, user)
    await message.answer(msg.PAUSE_OK)


# ---------------------------------------------------------------------------
# /resume
# ---------------------------------------------------------------------------

@router.message(Command("resume"))
async def cmd_resume(message: Message) -> None:
    loop = asyncio.get_event_loop()
    user = await loop.run_in_executor(None, _get_user, message.from_user.id)
    if user is None or user.state == UserState.DELETED:
        await message.answer(msg.NOT_ONBOARDED)
        return
    if user.state != UserState.PAUSED:
        await message.answer(msg.RESUME_NOT_PAUSED)
        return
    user.state = UserState.ACTIVE
    user.paused_until = None
    await loop.run_in_executor(None, _save_user, user)
    await message.answer(msg.RESUME_OK)
```

- [ ] **Step 3: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_commands.py::test_help_always_works tests/unit/test_commands.py::test_pause_sets_state_paused tests/unit/test_commands.py::test_pause_already_paused tests/unit/test_commands.py::test_resume_sets_state_active tests/unit/test_commands.py::test_guard_blocks_unknown_user -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add apps/bot/handlers/commands.py tests/unit/test_commands.py
git commit -m "feat: guard helper, /help, /pause, /resume commands"
```

---

## Task 7: /delete and /reonboard commands

**Files:**
- Modify: `apps/bot/handlers/commands.py`
- Modify: `tests/unit/test_commands.py`

- [ ] **Step 1: Write failing tests** — append to `tests/unit/test_commands.py`:

```python
@pytest.mark.asyncio
async def test_delete_confirm_flow():
    from apps.bot.handlers.commands import cmd_delete, cb_delete_yes
    msg2 = make_message(text="/delete")
    user = make_user_row(UserState.ACTIVE)
    with patch("apps.bot.handlers.commands._get_user", return_value=user):
        await cmd_delete(msg2)
        text = msg2.answer.call_args[0][0]
        assert "Удалить" in text

    cb = AsyncMock()
    cb.from_user = MagicMock(id=123)
    cb.message = AsyncMock()
    cb.answer = AsyncMock()
    with patch("apps.bot.handlers.commands._get_user", return_value=user), \
         patch("apps.bot.handlers.commands._wipe_user") as wipe_mock, \
         patch("apps.bot.handlers.commands._write_event"):
        await cb_delete_yes(cb)
        wipe_mock.assert_called_once_with(user)
        cb.message.answer.assert_called_once()


@pytest.mark.asyncio
async def test_reonboard_confirm_clears_state():
    from apps.bot.handlers.commands import cb_reonboard_yes
    storage = MemoryStorage()
    ctx = await make_ctx(storage)
    await ctx.update_data({"search_type": "whole_apt_solo"})

    cb = AsyncMock()
    cb.from_user = MagicMock(id=123, username="t")
    cb.message = AsyncMock()
    cb.answer = AsyncMock()

    user = make_user_row(UserState.ACTIVE)
    with patch("apps.bot.handlers.commands._get_user", return_value=user), \
         patch("apps.bot.handlers.commands._reset_user_prefs") as reset_mock:
        await cb_reonboard_yes(cb, ctx)
        reset_mock.assert_called_once_with(user)
```

Run:

```bash
uv run pytest tests/unit/test_commands.py::test_delete_confirm_flow tests/unit/test_commands.py::test_reonboard_confirm_clears_state -v
```

Expected: FAIL

- [ ] **Step 2: Add /delete and /reonboard to `apps/bot/handlers/commands.py`**

Append to `apps/bot/handlers/commands.py`:

```python
# ---------------------------------------------------------------------------
# /delete
# ---------------------------------------------------------------------------

def _wipe_user(user: User) -> None:
    with session_scope() as s:
        row = s.merge(user)
        row.state = UserState.DELETED
        row.search_type = None
        row.gender_pref = None
        row.agent_filter = None
        row.budget_min = None
        row.budget_max = None
        row.rooms = None
        row.areas = []
        row.move_in_window = None
        row.commute_origin = None
        row.commute_origin_lat = None
        row.commute_origin_lng = None
        row.commute_max_minutes = None
        row.commute_mode = None
        row.dealbreakers = []
        row.dealbreaker_keywords = []
        row.axis_priority = {}
        row.tradeoff_hint_text = None
        row.unacceptable_text = None
        row.instant_reject_text = None
        row.preference_embedding = None
        row.negative_area_mask = []
        row.distrust_set = []
        row.seen_set = []
        row.top_1pct_threshold = None


@router.message(Command("delete"))
async def cmd_delete(message: Message) -> None:
    if not await require_active_user(message):
        return
    await message.answer(
        msg.DELETE_CONFIRM,
        reply_markup=kb.confirm_kb(
            yes_data=kb.CB_DELETE_YES,
            no_data=kb.CB_DELETE_NO,
            yes_label="Да, удалить",
            no_label="Отмена",
        ),
    )


@router.callback_query(lambda c: c.data == kb.CB_DELETE_YES)
async def cb_delete_yes(callback: CallbackQuery) -> None:
    loop = asyncio.get_event_loop()
    user = await loop.run_in_executor(None, _get_user, callback.from_user.id)
    if user:
        await loop.run_in_executor(None, _wipe_user, user)
        await loop.run_in_executor(
            None, _write_event, "user_deleted", user.id
        )
    await callback.message.answer(msg.DELETE_DONE)
    await callback.answer()


@router.callback_query(lambda c: c.data == kb.CB_DELETE_NO)
async def cb_delete_no(callback: CallbackQuery) -> None:
    await callback.message.answer(msg.DELETE_CANCELLED)
    await callback.answer()


# ---------------------------------------------------------------------------
# /reonboard
# ---------------------------------------------------------------------------

def _reset_user_prefs(user: User) -> None:
    with session_scope() as s:
        row = s.merge(user)
        row.state = UserState.ONBOARDING
        row.search_type = None
        row.gender_pref = None
        row.agent_filter = None
        row.budget_min = None
        row.budget_max = None
        row.rooms = None
        row.areas = []
        row.move_in_window = None
        row.commute_origin = None
        row.commute_origin_lat = None
        row.commute_origin_lng = None
        row.commute_max_minutes = None
        row.commute_mode = None
        row.dealbreakers = []
        row.dealbreaker_keywords = []
        row.axis_priority = {}
        row.tradeoff_hint_text = None
        row.unacceptable_text = None
        row.instant_reject_text = None
        row.preference_embedding = None
        row.onboarded_at = None


@router.message(Command("reonboard"))
async def cmd_reonboard(message: Message) -> None:
    if not await require_active_user(message):
        return
    await message.answer(
        msg.REONBOARD_CONFIRM,
        reply_markup=kb.confirm_kb(
            yes_data=kb.CB_REONBOARD_YES,
            no_data=kb.CB_REONBOARD_NO,
        ),
    )


@router.callback_query(lambda c: c.data == kb.CB_REONBOARD_YES)
async def cb_reonboard_yes(callback: CallbackQuery, state: FSMContext) -> None:
    loop = asyncio.get_event_loop()
    user = await loop.run_in_executor(None, _get_user, callback.from_user.id)
    if user:
        await loop.run_in_executor(None, _reset_user_prefs, user)
    await state.clear()
    from apps.bot.handlers.onboarding import start_search_type
    await start_search_type(callback.message, state)
    await callback.answer()


@router.callback_query(lambda c: c.data == kb.CB_REONBOARD_NO)
async def cb_reonboard_no(callback: CallbackQuery) -> None:
    await callback.message.answer(msg.REONBOARD_CANCELLED)
    await callback.answer()
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/unit/test_commands.py -v
```

Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add apps/bot/handlers/commands.py tests/unit/test_commands.py
git commit -m "feat: /delete and /reonboard commands"
```

---

## Task 8: Onboarding FSM — WELCOME through COMMUTE_MODE

**Files:**
- Create: `apps/bot/handlers/onboarding.py` (partial — through state `commute_mode`)
- Create: `tests/unit/test_onboarding_flow.py` (partial)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_onboarding_flow.py`:

```python
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
```

Run:

```bash
uv run pytest tests/unit/test_onboarding_flow.py -v
```

Expected: FAIL — `No module named 'apps.bot.handlers.onboarding'`

- [ ] **Step 2: Create `apps/bot/handlers/onboarding.py`** (through commute_mode state)

```python
from __future__ import annotations

import asyncio
import logging

from aiogram import Router
from aiogram.filters import Command
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
    loop = asyncio.get_event_loop()
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
async def msg_budget_custom_max(message: Message, state: FSMContext) -> None:
    try:
        val = int(message.text.replace(" ", "").replace(",", ""))
    except ValueError:
        await message.answer("Введи число, например: 2500000")
        return
    await state.update_data(budget_max=val, _budget_custom_step="min")
    await message.answer(msg.ASK_BUDGET_CUSTOM_MIN)


# Add a second handler for the min value — we distinguish via stored _budget_custom_step
@router.message(Onboarding.budget_custom)
async def msg_budget_custom_min(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("_budget_custom_step") != "min":
        return  # not our turn — handled by msg_budget_custom_max above
    try:
        val = int(message.text.replace(" ", "").replace(",", ""))
    except ValueError:
        await message.answer("Введи число, например: 0")
        return
    await state.update_data(budget_min=val)
    await state.set_state(Onboarding.rooms)
    await message.answer(msg.ASK_ROOMS, reply_markup=kb.rooms_kb())
```

**Note on budget custom:** aiogram fires handlers in registration order; the second handler checks a sentinel key in FSMContext data (`_budget_custom_step`) to know which message it is. A simpler alternative is to use two distinct states (`budget_custom_max` and `budget_custom_min`). If this approach causes issues during testing, split into two states in `states.py` and adjust accordingly.

Continue adding to `apps/bot/handlers/onboarding.py`:

```python
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
```

- [ ] **Step 3: Run the tests**

```bash
uv run pytest tests/unit/test_onboarding_flow.py -v
```

Expected: PASS (all 7 tests)

- [ ] **Step 4: Commit**

```bash
git add apps/bot/handlers/onboarding.py tests/unit/test_onboarding_flow.py
git commit -m "feat: onboarding FSM states WELCOME through commute_mode"
```

---

## Task 9: Onboarding FSM — DEALBREAKERS through DONE + background profile build

**Files:**
- Modify: `apps/bot/handlers/onboarding.py` (complete remaining states)
- Modify: `tests/unit/test_onboarding_flow.py` (add remaining tests)

- [ ] **Step 1: Write failing tests** — append to `tests/unit/test_onboarding_flow.py`:

```python
@pytest.mark.asyncio
async def test_dealbreakers_done_requires_zero_or_more():
    from apps.bot.handlers.onboarding import cb_dealbreakers_done
    cb = make_cb("db_done")
    ctx = await make_ctx()
    await ctx.set_state(Onboarding.dealbreakers)
    await ctx.update_data(dealbreakers=[])
    await cb_dealbreakers_done(cb, ctx)
    state = await ctx.get_state()
    assert state == Onboarding.agent_filter


@pytest.mark.asyncio
async def test_axis_priority_iterates_then_advances():
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
async def test_free_text_wall_skip_goes_to_done_and_writes_db():
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
```

Run:

```bash
uv run pytest tests/unit/test_onboarding_flow.py -v
```

Expected: FAIL (new tests not found yet)

- [ ] **Step 2: Complete `apps/bot/handlers/onboarding.py`**

Append to `apps/bot/handlers/onboarding.py`:

```python
# ---------------------------------------------------------------------------
# dealbreakers (multi-select)
# ---------------------------------------------------------------------------

@router.callback_query(lambda c: c.data and c.data.startswith(f"{kb.CB_DB_TOGGLE}:"))
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


@router.callback_query(lambda c: c.data == kb.CB_DB_DONE)
async def cb_dealbreakers_done(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Onboarding.agent_filter)
    await callback.message.answer(msg.ASK_AGENT_FILTER,
                                  reply_markup=kb.agent_filter_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# agent_filter
# ---------------------------------------------------------------------------

@router.callback_query(lambda c: c.data and c.data.startswith(f"{kb.CB_AGENT_FILTER}:"))
async def cb_agent_filter(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    await state.update_data(agent_filter=value)
    data = await state.get_data()
    # Build pending_axes list; skip commute if no origin
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

@router.callback_query(lambda c: c.data and c.data.startswith(f"{kb.CB_AXIS}:"))
async def cb_axis_priority(callback: CallbackQuery, state: FSMContext) -> None:
    _, priority, axis_key = callback.data.split(":")
    data = await state.get_data()
    axis_priority: dict = dict(data.get("axis_priority", {}))
    axis_priority[axis_key] = priority.upper()  # "MUST" or "NICE"
    pending: list[str] = list(data.get("pending_axes", []))
    pending = [a for a in pending if a != axis_key]
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

@router.callback_query(lambda c: c.data and c.data.startswith(f"{kb.CB_FREE_TEXT_WALL}:"))
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


@router.callback_query(lambda c: c.data == kb.CB_FREE_TEXT_SKIP)
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
    loop = asyncio.get_event_loop()
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

    # 1. Extract dealbreaker keywords from instant_reject_text (if present)
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
```

- [ ] **Step 3: Run all onboarding tests**

```bash
uv run pytest tests/unit/test_onboarding_flow.py -v
```

Expected: PASS (all tests)

- [ ] **Step 4: Commit**

```bash
git add apps/bot/handlers/onboarding.py tests/unit/test_onboarding_flow.py
git commit -m "feat: onboarding FSM complete, DEALBREAKERS through DONE with background profile build"
```

---

## Task 10: /settings handler

**Files:**
- Create: `apps/bot/handlers/settings.py`

No new test file — coverage comes from testing that handler imports work and the router attaches. Full manual testing for the settings flow (it reuses all the same onboarding handler functions, just called from a different entry point).

- [ ] **Step 1: Write a minimal failing import test** — append to `tests/unit/test_commands.py`:

```python
def test_settings_router_importable():
    from apps.bot.handlers.settings import router
    assert router is not None
```

Run:

```bash
uv run pytest tests/unit/test_commands.py::test_settings_router_importable -v
```

Expected: FAIL

- [ ] **Step 2: Create `apps/bot/handlers/settings.py`**

```python
from __future__ import annotations

import asyncio
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from apps.bot import keyboards as kb
from apps.bot import messages as msg
from apps.bot.handlers.commands import _get_user, _save_user, require_active_user
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

    # Store which axis we're editing so the save step knows what to update
    await state.update_data(_editing_axis=axis)

    if axis == "budget":
        await state.set_state(Settings.edit_budget)
        await callback.message.answer(msg.ASK_BUDGET, reply_markup=kb.budget_kb())

    elif axis == "areas":
        loop = asyncio.get_event_loop()
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
        loop = asyncio.get_event_loop()
        user = await loop.run_in_executor(None, _get_user, callback.from_user.id)
        current = user.dealbreakers if user else []
        await state.update_data(dealbreakers=list(current))
        await state.set_state(Settings.edit_dealbreakers)
        await callback.message.answer(msg.ASK_DEALBREAKERS,
                                      reply_markup=kb.dealbreakers_kb(current))

    await callback.answer()


# ---------------------------------------------------------------------------
# Settings edit completions — each saves the relevant field and returns to menu
# ---------------------------------------------------------------------------

async def _finish_settings_edit(
    message: Message, state: FSMContext, fields: dict
) -> None:
    """Save updated fields to the User row, rebuild embedding if needed, return to menu."""
    loop = asyncio.get_event_loop()
    tg_user_id = message.from_user.id
    pref_affecting = {"budget_min", "budget_max", "areas", "search_type",
                      "commute_origin", "commute_origin_lat", "commute_origin_lng",
                      "commute_max_minutes", "commute_mode", "dealbreakers"}

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
    loop = asyncio.get_event_loop()
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


# Settings-specific callback handlers that complete an edit step
# and call _finish_settings_edit.

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
    await _finish_settings_edit(callback.message, state, {"search_type": value})
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
        {"commute_origin": None, "commute_origin_lat": None,
         "commute_origin_lng": None, "commute_max_minutes": None,
         "commute_mode": None}
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
async def cb_settings_commute_minutes(callback: CallbackQuery, state: FSMContext) -> None:
    val = int(callback.data.split(":")[1])
    await state.update_data(commute_max_minutes=val)
    await state.set_state(Settings.edit_commute_mode)
    await callback.message.answer(msg.ASK_COMMUTE_MODE, reply_markup=kb.commute_mode_kb())
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
        callback.message, state, {"dealbreakers": data.get("dealbreakers", [])}
    )
    await callback.answer()
```

- [ ] **Step 3: Run the test**

```bash
uv run pytest tests/unit/test_commands.py::test_settings_router_importable -v
```

Expected: PASS

- [ ] **Step 4: Run the full unit test suite**

```bash
uv run pytest tests/unit/ -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add apps/bot/handlers/settings.py tests/unit/test_commands.py
git commit -m "feat: /settings per-axis edit handler"
```

---

## Task 11: Bot main.py — Dispatcher + webhook server

**Files:**
- Create: `apps/bot/main.py`

- [ ] **Step 1: Write a failing import test** — append to `tests/unit/test_commands.py`:

```python
def test_bot_main_importable():
    # Verifies the module imports without raising (token can be empty in test env)
    import importlib
    import sys
    # Temporarily patch settings so import doesn't fail on empty token
    from unittest.mock import patch
    with patch("apps.shared.config.settings") as mock_settings:
        mock_settings.telegram_bot_token = "123456789:AAFakeTokenForTestingOnly123456789"
        mock_settings.telegram_webhook_url = "https://example.com/bot/webhook"
        mock_settings.telegram_webhook_secret = ""
        mock_settings.redis_url = "redis://localhost:6379/0"
        # Force reimport
        sys.modules.pop("apps.bot.main", None)
        mod = importlib.import_module("apps.bot.main")
        assert hasattr(mod, "dp")
```

Run:

```bash
uv run pytest tests/unit/test_commands.py::test_bot_main_importable -v
```

Expected: FAIL

- [ ] **Step 2: Create `apps/bot/main.py`**

```python
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from apps.bot.handlers import commands, onboarding, settings as settings_handler
from apps.shared.config import settings

log = logging.getLogger(__name__)

bot = Bot(
    token=settings.telegram_bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
storage = RedisStorage.from_url(settings.redis_url)
dp = Dispatcher(storage=storage)

dp.include_router(onboarding.router)
dp.include_router(settings_handler.router)
dp.include_router(commands.router)


async def on_startup(bot: Bot) -> None:
    secret = settings.telegram_webhook_secret or None
    await bot.set_webhook(
        url=settings.telegram_webhook_url,
        secret_token=secret,
        drop_pending_updates=True,
    )
    log.info("Webhook registered: %s", settings.telegram_webhook_url)


async def on_shutdown(bot: Bot) -> None:
    await bot.delete_webhook()
    log.info("Webhook removed")


dp.startup.register(on_startup)
dp.shutdown.register(on_shutdown)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    app = web.Application()
    secret = settings.telegram_webhook_secret or None
    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=secret,
    ).register(app, path="/webhook")
    setup_application(app, dp, bot=bot)
    web.run_app(app, host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the test**

```bash
uv run pytest tests/unit/test_commands.py::test_bot_main_importable -v
```

Expected: PASS

- [ ] **Step 4: Run full unit suite**

```bash
uv run pytest tests/unit/ -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add apps/bot/main.py tests/unit/test_commands.py
git commit -m "feat: bot main.py — Dispatcher + aiohttp webhook server"
```

---

## Task 12: docker-compose + nginx

**Files:**
- Modify: `docker-compose.yml`
- Create: `infra/nginx.conf`

No unit tests for infra. Manual verification after deploy.

- [ ] **Step 1: Create `infra/nginx.conf`**

```bash
mkdir -p /home/maurilar/petties/apt/infra
```

```nginx
# infra/nginx.conf
server {
    listen 80;
    server_name _;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name _;

    ssl_certificate     /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;

    location /bot/webhook {
        proxy_pass         http://bot:8080/webhook;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_read_timeout 10s;
    }

    location /health {
        proxy_pass http://api:8000/health;
    }
}
```

Note: `${DOMAIN}` is substituted at container start via `envsubst` (see nginx service command below). If you don't have a cert yet, use the `certbot` certonly flow first, then mount the letsencrypt volume.

- [ ] **Step 2: Add `bot` and `nginx` services to `docker-compose.yml`**

Current `docker-compose.yml` ends at the `volumes:` block. Add the following services before `volumes:`:

```yaml
  bot:
    build: .
    command: python -m apps.bot.main
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped

  nginx:
    image: nginx:1.27-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./infra/nginx.conf:/etc/nginx/templates/default.conf.template:ro
      - /etc/letsencrypt:/etc/letsencrypt:ro
    environment:
      - DOMAIN=${DOMAIN}
    command: >
      sh -c "envsubst '$$DOMAIN' < /etc/nginx/templates/default.conf.template
             > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"
    depends_on:
      - bot
      - api
    restart: unless-stopped
```

Also add `DOMAIN=yourdomain.com` to `.env.example`.

- [ ] **Step 3: Verify compose config parses**

```bash
docker compose config --quiet
```

Expected: no output (no errors)

- [ ] **Step 4: Build the bot image**

```bash
docker compose build bot
```

Expected: build succeeds, no import errors in the final layer.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml infra/nginx.conf
git commit -m "feat: add bot and nginx services to docker-compose"
```

---

## Self-review checklist

After writing: skim spec, verify task coverage.

| Spec requirement | Task |
|---|---|
| aiogram bot, /start | Task 8 |
| Structured 10-step onboarding | Tasks 8, 9 |
| Free-text wall (3 questions) | Task 9 |
| Background Gemini keyword extraction + embedding | Task 9 |
| /settings per-axis edit | Task 10 |
| /reonboard | Task 7 |
| /pause, /resume | Task 6 |
| /delete (row kept, fields wiped) | Task 7 |
| /help | Task 6 |
| Guard middleware | Task 6 |
| Webhook via nginx | Task 12 |
| RedisStorage FSM | Task 11 |
| User + Event tables | Task 1 |
| Alembic migration | Task 2 |
| Commute step optional | Task 8 (cb_commute_skip) |
| Commute axis excluded if no origin | Task 9 (cb_agent_filter builds pending_axes) |
| Uведomления stub | Task 10 |
| build_user_pref_text for settings re-embed | Task 3, Task 10 |

All spec requirements covered. No TBDs or placeholders in any task.
