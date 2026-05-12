# Admin Panel + Onboarding Cleanup — Design Spec

**Date:** 2026-05-12
**Status:** Approved

---

## 1. Admin Panel

### Goal

A lightweight, read/write web UI for operational oversight: KPI metrics, user management, listing suppression, and scrape health. Accessible from phone or laptop browser. Manual refresh only.

### Architecture

Extend `apps/api/` with an `/admin` router mounted in the existing FastAPI app. No new Docker service. Nginx already routes to `api:8000`; the panel is reachable at `https://scout.golibabdullayev.uz/admin`.

**New files:**
```
apps/api/
  router_admin.py
  templates/
    admin_base.html      # base layout, nav bar
    admin_kpi.html
    admin_users.html
    admin_listings.html
    admin_scrape.html
```

**New dependency:** `jinja2>=3.1` added to `pyproject.toml`.

**New env var:** `ADMIN_TOKEN` — a secret string set in `.env`.

### Authentication

1. Visit `/admin?token=ADMIN_TOKEN` once per browser.
2. Server validates token == `settings.admin_token`. On match, sets `admin_session` cookie (HttpOnly, SameSite=Strict, value = token).
3. A `require_admin` FastAPI dependency (used on every `/admin/*` route) reads the cookie and returns HTTP 403 if missing or wrong.
4. No user table, no bcrypt, no sessions database.

### Pages

| Page | Route | Data |
|------|-------|------|
| KPI Dashboard | `GET /admin` | `like_rate`, `contact_rate`, `mute_rate`, `days_to_success` from `apps/shared/kpi.py` (30-day window) |
| Users | `GET /admin/users` | `User` table — tg_username, state, budget_min/max, areas, onboarded_at, last_active_at. POST actions: pause, resume, delete |
| Listings | `GET /admin/listings` | `Listing` table — title, state, risk_score, suppressed, source_url. Filter by state via query param. POST action: toggle suppressed |
| Scrape Health | `GET /admin/scrape` | `ScrapeRunHealth` — last 24h rows grouped by category, showing success/failure counts and playwright fallback flag |

### Styling

Single `<link>` to Pico.css CDN (classless, ~10 KB). No build step. Renders cleanly on mobile and desktop.

### Write Actions

All write actions (pause/resume/delete user, suppress/unsuppress listing) are `POST` endpoints that redirect back to the originating page after committing the change. No AJAX.

---

## 2. Onboarding Message Cleanup

### Goal

Keep the onboarding chat clean: every answered question (bot message + buttons, user typed text) disappears before the next one appears.

### Pattern

Two helpers added at the top of `apps/bot/handlers/onboarding.py`:

```python
async def _track(state: FSMContext, *msg_ids: int) -> None:
    """Append message IDs to the pending-delete list in FSM state."""
    data = await state.get_data()
    ids = list(data.get("_del_ids", []))
    ids.extend(msg_ids)
    await state.update_data(_del_ids=ids)

async def _flush(bot: Bot, chat_id: int, state: FSMContext) -> None:
    """Delete all tracked messages and clear the list. Errors suppressed."""
    data = await state.get_data()
    for mid in data.get("_del_ids", []):
        with suppress(Exception):
            await bot.delete_message(chat_id, mid)
    await state.update_data(_del_ids=[])
```

### Rules Per Handler Type

**Callback handlers (button tap):**
1. `await callback.message.delete()` — removes the answered question immediately.
2. Transition state.
3. Send next question; call `_track(state, sent.message_id)`.

**Text handlers (typed reply):**
1. `await message.delete()` — removes user's text immediately.
2. `await _flush(bot, message.chat.id, state)` — removes bot's preceding prompt(s).
3. Transition state.
4. Send next question; call `_track(state, sent.message_id)`.

**Multi-select steps (areas, dealbreakers):**
- Toggle taps use `edit_reply_markup` — message is not deleted mid-selection.
- "Done" tap: treated as a callback handler (delete the multi-select message, send next question).

**Error / retry messages** (e.g. geocode failed, invalid budget input):
- Tracked via `_track()` immediately after sending so they are swept on the next valid answer.

### What Survives

The final "Building your profile…" and "✅ You're all set!" messages are not tracked — they are the conclusion of onboarding, not transient noise.

### Bot Injection

`bot: Bot` is added to handler signatures where needed. aiogram 3 injects it automatically via its DI system — no global bot reference required.

### Scope

Changes are confined to `apps/bot/handlers/onboarding.py`. No other handlers are affected.
