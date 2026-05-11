# Scout — Plan 2: Bot Onboarding Design Spec

**Status:** approved (2026-05-10)
**Scope:** aiogram Telegram bot, webhook wiring, full onboarding FSM, /settings per-axis edit, /reonboard, /pause, /resume, /delete
**Follows:** Plan 1 (ingestion pipeline complete and smoke-tested)
**Precedes:** Plan 3 (match fanout, scoring, digest delivery, instant alerts)

---

## 1. Architecture

The bot runs as a new `bot` service in docker-compose, separate from the existing `api`, `worker`, and `beat` services. It owns the aiogram `Dispatcher`, mounts a lightweight aiohttp webhook server on port 8080, and registers its webhook URL with Telegram on startup. Nginx terminates TLS and reverse-proxies `POST /bot/webhook` to `bot:8080/webhook`.

The bot shares `apps/shared/` (models, db, config, enrichment functions) with the existing workers. No new shared infrastructure — same Postgres, same Redis (also used for aiogram's `RedisStorage` FSM state).

Three new config vars:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_WEBHOOK_URL` (e.g. `https://yourdomain.com/bot/webhook`)
- `TELEGRAM_WEBHOOK_SECRET` (used as `X-Telegram-Bot-Api-Secret-Token` for webhook verification)

One new Alembic migration adds `users` and `events` tables. `matches` is Plan 3.

---

## 2. File Structure

```
apps/bot/
├── __init__.py
├── main.py              # Dispatcher setup, aiohttp webhook server startup/shutdown
├── states.py            # OnboardingStates FSM enum (one state per step)
├── messages.py          # All Russian-language message text constants
├── keyboards.py         # InlineKeyboardMarkup builders for each step
└── handlers/
    ├── __init__.py
    ├── onboarding.py    # /start + full 17-state onboarding FSM
    ├── settings.py      # /settings per-axis edit flow
    └── commands.py      # /reonboard, /pause, /resume, /delete, /help

apps/shared/
└── models.py            # +User, +Event appended to existing file

alembic/versions/
└── <hash>_add_users_events.py

apps/shared/config.py    # +telegram_bot_token, webhook_url, webhook_secret
docker-compose.yml       # +bot service + nginx service (Plan 1 had no nginx)
infra/nginx.conf         # new file: TLS termination + /bot/webhook proxy block

tests/unit/
├── test_onboarding_flow.py
├── test_user_model.py
└── test_commands.py
```

`messages.py` and `keyboards.py` are separated from handlers so all bot-facing text lives in one reviewable file and keyboard builders stay independently testable.

---

## 3. Data Model

### 3.1 `users` table

```sql
users (
  id                      BIGSERIAL PRIMARY KEY,
  tg_user_id              BIGINT UNIQUE NOT NULL,
  tg_username             TEXT,

  -- structured prefs (nullable until onboarding completes)
  search_type             VARCHAR(32),
  gender_pref             VARCHAR(8),
  agent_filter            VARCHAR(16),
  budget_min              BIGINT,
  budget_max              BIGINT,
  rooms                   INTEGER,          -- NULL = any
  areas                   TEXT[],
  move_in_window          VARCHAR(16),

  commute_origin          TEXT,             -- NULL if user skipped
  commute_origin_lat      FLOAT,
  commute_origin_lng      FLOAT,
  commute_max_minutes     INTEGER,
  commute_mode            VARCHAR(8),

  dealbreakers            TEXT[],
  dealbreaker_keywords    TEXT[],
  axis_priority           JSONB,

  tradeoff_hint_text      TEXT,
  unacceptable_text       TEXT,
  instant_reject_text     TEXT,
  preference_embedding    vector(3072),     -- matches settings.embedding_dim

  negative_area_mask      TEXT[],
  distrust_set            TEXT[],
  seen_set                BIGINT[],
  top_1pct_threshold      FLOAT,

  state                   VARCHAR(16) NOT NULL DEFAULT 'onboarding',
                          -- onboarding | active | paused | success | deleted
  paused_until            TIMESTAMPTZ,
  success_at              TIMESTAMPTZ,
  onboarded_at            TIMESTAMPTZ,
  last_active_at          TIMESTAMPTZ,
  created_at              TIMESTAMPTZ DEFAULT now(),
  updated_at              TIMESTAMPTZ DEFAULT now()
);
```

`preference_embedding` is `vector(3072)` — consistent with `settings.embedding_dim` (resized in Plan 1; the spec says 768d but the codebase already uses 3072d).

### 3.2 `events` table

Append-only telemetry. Plan 2 writes `onboarding_started`, `onboarding_completed`, `command_pause`, `command_resume`, `command_delete`, `command_reonboard` events. Plan 3 adds match/delivery events.

```sql
events (
  id          BIGSERIAL PRIMARY KEY,
  ts          TIMESTAMPTZ DEFAULT now(),
  kind        TEXT NOT NULL,
  user_id     BIGINT,
  listing_id  BIGINT,
  match_id    BIGINT,
  payload     JSONB DEFAULT '{}'
);
```

No hard foreign keys — avoids cascade complexity across plans.

---

## 4. Onboarding FSM

17 states. Each state sends one message with buttons, waits for a callback or text input, validates, writes to `FSMContext` data, then advances.

```
WELCOME
  → tap [Начать ▶️]
SEARCH_TYPE         4 buttons: whole_apt_family / whole_apt_solo / shared_room / looking_for_roommate
  → if shared_room or looking_for_roommate → GENDER_PREF
  → else → BUDGET
GENDER_PREF         3 buttons: any / male / female
BUDGET              5 preset ranges + [Ввести свой] free-text fallback
ROOMS               5 buttons: любое / 1 / 2 / 3 / 4+
AREAS               multi-select grid (12 tumans) + [+ Свой район] free-text
                    [Готово ✓] advances once ≥1 selected
MOVE_IN             4 buttons: сейчас / 2 недели / месяц / гибко
COMMUTE_ORIGIN      free-text input + [Пропустить]
  → if skipped → DEALBREAKERS
  → if provided → geocode via Yandex → store lat/lng → COMMUTE_MINUTES
COMMUTE_MINUTES     5 preset buttons: 15 / 20 / 30 / 45 / 60 мин
COMMUTE_MODE        3 buttons: пешком / на машине / общественный
DEALBREAKERS        multi-select + [Готово ✓]
AGENT_FILTER        2 buttons: только хозяин / агенты тоже ок
AXIS_PRIORITY       iterates axes one at a time via FSMContext list
                    (budget, area, commute [skipped if no origin], rooms, furnishing)
                    each: [Обязательно] / [Желательно]
FREE_TEXT_WALL      [Да, уточню] / [Пропустить]
  → if skip → DONE
FREE_TEXT_1         (1/3) tradeoff hint + [Пропустить]
FREE_TEXT_2         (2/3) unacceptable text + [Пропустить]
FREE_TEXT_3         (3/3) instant reject + [Пропустить]
DONE                background: Gemini keyword extraction + embedding build
                    → user.state = 'active', user.onboarded_at = now()
                    → confirmation message sent
```

### Multi-select steps (AREAS, DEALBREAKERS)

Inline keyboard with toggle buttons. Tapping a button fires a callback that flips the selection (adds/removes from FSMContext list) and edits the keyboard in-place via `message.edit_reply_markup`. A separate `[Готово ✓]` button advances the state once ≥1 option is selected.

### AXIS_PRIORITY iteration

The FSM stores a `pending_axes` list in FSMContext data. Each handler pops one axis, displays it with two buttons, stores the result (`MUST` / `NICE`), then either shows the next axis or transitions to FREE_TEXT_WALL. This avoids creating a separate FSM state per axis.

### Background profile build (DONE state)

After the last answer (or skip at FREE_TEXT_WALL), the bot sends "⏳ Настраиваю профиль..." and runs async:
1. If `instant_reject_text` is present: Gemini 2.5 Flash extracts keywords → stored as `dealbreaker_keywords[]`.
2. Serialized representation of all prefs → Gemini text-embedding-004 → `preference_embedding`.
3. `User` row flushed to DB with `state = active`, `onboarded_at = now()`.
4. Bot sends confirmation message.

If Gemini calls fail (rate limit, network), keyword extraction is skipped (non-critical) and embedding falls back to a zero vector — the user is still marked active. A retry can be triggered manually via `/reonboard`.

---

## 5. Bot Commands

### `/settings`

Inline keyboard with 7 axes. Tapping one re-enters a mini-FSM that runs just that step, reusing the same handler logic and keyboard builders as onboarding. On confirm, the user row is updated; if the changed axis affects preferences (budget, areas, search type, commute, dealbreakers), `preference_embedding` is rebuilt in the background. Returns to the settings menu after each edit.

```
[ 💰 Бюджет ]        [ 📍 Районы ]
[ 🏠 Тип поиска ]    [ 👤 Пол ]
[ 🚇 Маршрут ]       [ 🚫 Стоп-факторы ]
[ 🔔 Уведомления ]
```

`[🔔 Уведомления]` in Plan 2 is a stub: sends "Настройки уведомлений появятся после запуска подборок (план 3)." and returns to the menu.

### `/reonboard`

Confirms with "Начнём заново? Все текущие настройки будут заменены. [ Да ] [ Отмена ]". On confirm: clears FSMContext and resets user pref fields (keeps `tg_user_id`, `created_at`, feedback history), then re-enters SEARCH_TYPE state.

### `/pause`

If `state = active`: sets `state = paused`, `paused_until = NULL` (indefinite). Confirms "Поиск на паузе. /resume чтобы возобновить."
If already paused: "Уже на паузе."

### `/resume`

If `state = paused`: sets `state = active`, clears `paused_until`. Confirms "Поиск возобновлён ✅."
If not paused: "Поиск уже активен."

### `/delete`

Sends "⚠️ Удалить все данные? Это необратимо. [ Да, удалить ] [ Отмена ]". On confirm: sets all nullable pref columns to NULL, sets `state = deleted` (row is NOT deleted — `tg_user_id` uniqueness is preserved so the user can `/start` again later), writes `event(kind='user_deleted')`, sends "Готово. Все данные удалены."

### `/help`

Sends the help text from spec §3.2. Always works regardless of onboarding state.

### Guard middleware

All commands except `/start` and `/help` check that a `User` row exists with `state != deleted`. If missing or onboarding incomplete → "Сначала пройди онбординг — /start".

---

## 6. Webhook Wiring

### docker-compose.yml — new `bot` service

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
```

No exposed port — nginx reaches it on `bot:8080` via the internal Docker network.

### nginx — new location block

```nginx
location /bot/webhook {
    proxy_pass http://bot:8080/webhook;
    proxy_set_header Host $host;
}
```

### `apps/bot/main.py` startup sequence

1. `Bot(token=settings.telegram_bot_token)`
2. `Dispatcher(storage=RedisStorage.from_url(settings.redis_url))`
3. Register routers: onboarding, settings, commands.
4. On `startup`: `bot.set_webhook(url=settings.telegram_webhook_url, secret_token=settings.telegram_webhook_secret)`
5. Start `aiohttp.web.Application` on `0.0.0.0:8080` via `SimpleRequestHandler`.
6. On `shutdown`: `bot.delete_webhook()`

### Local dev

Run `ngrok http 8080`, set `TELEGRAM_WEBHOOK_URL=https://<ngrok-id>.ngrok.io/bot/webhook` in `.env`. No code change needed. Documented in the runbook.

---

## 7. Testing

Unit-only. No live Telegram connection.

**`test_onboarding_flow.py`** — aiogram `MockedBot` + `MemoryStorage` (swap for tests). Tests:
- Happy path: all 17 states advance, FSMContext accumulates correct fields, `User` written at DONE.
- `gender_pref` step skipped when `search_type = whole_apt_family`.
- Commute steps skipped when origin is skipped.
- Free-text wall skip path writes `User` without free-text fields.

**`test_user_model.py`** — testcontainers Postgres. Verifies migration creates both tables, `tg_user_id` unique constraint holds, `state` transitions write correctly.

**`test_commands.py`** — guard middleware blocks unregistered user, `/pause`/`/resume` toggle `state` correctly, `/delete` wipes user fields.

Manual verify: chat with bot end-to-end, confirm `users` row in Postgres with correct fields and non-null `preference_embedding`.

---

## 8. Out of Scope (deferred to Plans 3 & 4)

- Match fanout, scoring, digest delivery, instant alerts
- 👍 / 👎 feedback buttons and embedding updates
- 48h / 5d KPI chase follow-ups
- Sunday weekly status check-in
- `Уведомления` settings (stub only in Plan 2)
- Full free-text preference re-edit via `/settings` (only structured axes editable in Plan 2)
