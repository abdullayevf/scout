# Admin Panel + Onboarding Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lightweight Jinja2-based web admin panel to the existing FastAPI service, and make the Telegram onboarding flow delete each answered question immediately to keep the chat clean.

**Architecture:** Admin panel extends `apps/api/` with a new router, Jinja2 templates, and token-cookie auth — no new Docker service or JS build step. Onboarding cleanup adds two async helper functions (`_track`, `_flush`) to `apps/bot/handlers/onboarding.py` and applies a uniform delete pattern across all handlers.

**Tech Stack:** FastAPI, Jinja2, Pico.css (CDN), aiogram 3, SQLAlchemy, existing `apps/shared/kpi.py`

> **Note:** These two features are fully independent. If you need to pause, the admin panel (Part A, Tasks 1–7) and onboarding cleanup (Part B, Tasks 9–13) can be implemented and shipped separately.

---

## File Map

**Created:**
- `apps/api/router_admin.py` — all `/admin/*` routes + `require_admin` dependency
- `apps/api/templates/admin_base.html` — base layout + nav
- `apps/api/templates/admin_kpi.html`
- `apps/api/templates/admin_users.html`
- `apps/api/templates/admin_listings.html`
- `apps/api/templates/admin_scrape.html`
- `tests/unit/test_admin_auth.py`
- `tests/unit/test_onboarding_cleanup.py`

**Modified:**
- `apps/shared/config.py` — add `admin_token: str = ""`
- `apps/api/main.py` — add Jinja2Templates + include admin router
- `pyproject.toml` — add `jinja2>=3.1`
- `apps/bot/handlers/onboarding.py` — add helpers, apply delete pattern
- `.env.example` — add `ADMIN_TOKEN=`

---

## Part A — Admin Panel

### Task 1: Config, dependency, env template

**Files:**
- Modify: `apps/shared/config.py`
- Modify: `pyproject.toml`
- Modify: `.env.example`

- [ ] **Step 1: Add `admin_token` field to Settings**

In `apps/shared/config.py`, add one line after `telegram_webhook_secret`:

```python
    telegram_webhook_secret: str = ""

    admin_token: str = ""  # add this line
```

- [ ] **Step 2: Add `jinja2` to dependencies**

In `pyproject.toml`, add inside the `dependencies` list:

```toml
  "jinja2>=3.1",
```

Full updated list (add after `"python-dotenv>=1.0",`):
```toml
  "python-dotenv>=1.0",
  "jinja2>=3.1",
```

- [ ] **Step 3: Add env var to example file**

In `.env.example`, add:
```
ADMIN_TOKEN=change-me-before-deploy
```

- [ ] **Step 4: Install new dependency**

```bash
uv sync
```

Expected: resolves jinja2, no errors.

- [ ] **Step 5: Commit**

```bash
git add apps/shared/config.py pyproject.toml uv.lock .env.example
git commit -m "feat(admin): add ADMIN_TOKEN config field and jinja2 dep"
```

---

### Task 2: Auth dependency + login route (TDD)

**Files:**
- Create: `apps/api/router_admin.py`
- Create: `tests/unit/test_admin_auth.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_admin_auth.py`:

```python
import pytest
from fastapi import HTTPException


def test_require_admin_valid_token(monkeypatch):
    from apps.shared.config import settings
    from apps.api.router_admin import require_admin
    monkeypatch.setattr(settings, "admin_token", "test-secret")
    require_admin(admin_session="test-secret")  # must not raise


def test_require_admin_wrong_token(monkeypatch):
    from apps.shared.config import settings
    from apps.api.router_admin import require_admin
    monkeypatch.setattr(settings, "admin_token", "test-secret")
    with pytest.raises(HTTPException) as exc:
        require_admin(admin_session="wrong")
    assert exc.value.status_code == 403


def test_require_admin_empty_app_token(monkeypatch):
    from apps.shared.config import settings
    from apps.api.router_admin import require_admin
    monkeypatch.setattr(settings, "admin_token", "")
    with pytest.raises(HTTPException) as exc:
        require_admin(admin_session="")
    assert exc.value.status_code == 403
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/unit/test_admin_auth.py -v
```

Expected: ImportError or ModuleNotFoundError — `router_admin` does not exist yet.

- [ ] **Step 3: Create `apps/api/router_admin.py` with auth only**

```python
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from apps.shared import kpi
from apps.shared.config import settings
from apps.shared.db import session_scope
from apps.shared.enums import ListingState, UserState
from apps.shared.models import Listing, ScrapeRunHealth, User
from sqlalchemy import desc, func, select

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def require_admin(admin_session: str = Cookie(default="")) -> None:
    if not settings.admin_token or admin_session != settings.admin_token:
        raise HTTPException(status_code=403, detail="Forbidden")


@router.get("/login")
def admin_login(token: str = Query(default="")) -> RedirectResponse:
    if not settings.admin_token or token != settings.admin_token:
        raise HTTPException(status_code=403, detail="Forbidden")
    resp = RedirectResponse(url="/admin", status_code=302)
    resp.set_cookie("admin_session", token, httponly=True, samesite="strict")
    return resp
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/unit/test_admin_auth.py -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/api/router_admin.py tests/unit/test_admin_auth.py
git commit -m "feat(admin): auth dependency and login route with tests"
```

---

### Task 3: Base template + Jinja2 wired into FastAPI

**Files:**
- Create: `apps/api/templates/admin_base.html`
- Modify: `apps/api/main.py`

- [ ] **Step 1: Create templates directory**

```bash
mkdir -p apps/api/templates
```

- [ ] **Step 2: Create base template**

Create `apps/api/templates/admin_base.html`:

```html
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Scout Admin</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
  <style>
    nav { border-bottom: 1px solid var(--pico-muted-border-color); margin-bottom: 1.5rem; }
    table { font-size: 0.875rem; }
    .badge { display: inline-block; padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.75rem; }
    .badge-ok { background: var(--pico-ins-color); }
    .badge-warn { background: var(--pico-del-color); }
  </style>
</head>
<body>
  <nav class="container-fluid">
    <ul><li><strong>🏠 Scout Admin</strong></li></ul>
    <ul>
      <li><a href="/admin">KPI</a></li>
      <li><a href="/admin/users">Users</a></li>
      <li><a href="/admin/listings">Listings</a></li>
      <li><a href="/admin/scrape">Scrape</a></li>
    </ul>
  </nav>
  <main class="container">
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

- [ ] **Step 3: Wire admin router into FastAPI app**

Replace `apps/api/main.py` with:

```python
from fastapi import FastAPI

from apps.api.router_admin import router as admin_router

app = FastAPI(title="Scout API", version="0.0.1")
app.include_router(admin_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: Smoke-test the server starts**

```bash
uv run uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
```

Expected: Uvicorn starts, no import errors. Stop with Ctrl+C.

- [ ] **Step 5: Commit**

```bash
git add apps/api/main.py apps/api/templates/admin_base.html
git commit -m "feat(admin): wire Jinja2 and admin router into FastAPI app"
```

---

### Task 4: KPI dashboard page

**Files:**
- Modify: `apps/api/router_admin.py`
- Create: `apps/api/templates/admin_kpi.html`

- [ ] **Step 1: Add KPI route to router**

Append to `apps/api/router_admin.py`:

```python
@router.get("", response_class=HTMLResponse)
def page_kpi(request: Request, _: None = Depends(require_admin)) -> HTMLResponse:
    with session_scope() as s:
        ctx = {
            "like_rate": kpi.like_rate(s),
            "contact_rate": kpi.contact_rate(s),
            "mute_rate": kpi.mute_rate(s),
            "days_to_success": kpi.days_to_success(s),
        }
    return templates.TemplateResponse("admin_kpi.html", {"request": request, **ctx})
```

- [ ] **Step 2: Create KPI template**

Create `apps/api/templates/admin_kpi.html`:

```html
{% extends "admin_base.html" %}
{% block content %}
<h2>KPI Dashboard <small style="font-size:0.6em;color:var(--pico-muted-color)">(30-day window)</small></h2>
<div class="grid">
  <article>
    <header>Like Rate</header>
    <p style="font-size:2rem;margin:0">{{ "%.1f"|format(like_rate * 100) }}%</p>
    <footer>liked + contacted + rented / all reacted</footer>
  </article>
  <article>
    <header>Contact Rate</header>
    <p style="font-size:2rem;margin:0">{{ "%.1f"|format(contact_rate * 100) }}%</p>
    <footer>contacted + rented / all reacted</footer>
  </article>
  <article>
    <header>Mute Rate</header>
    <p style="font-size:2rem;margin:0">{{ "%.1f"|format(mute_rate * 100) }}%</p>
    <footer>active users with zero reactions</footer>
  </article>
  <article>
    <header>Median Days to Success</header>
    <p style="font-size:2rem;margin:0">
      {% if days_to_success %}{{ "%.1f"|format(days_to_success) }}d{% else %}—{% endif %}
    </p>
    <footer>signup → apartment found</footer>
  </article>
</div>
{% endblock %}
```

- [ ] **Step 3: Manual verification**

Set `ADMIN_TOKEN=test` in `.env`, start the server, visit `http://localhost:8000/admin/login?token=test` in a browser. Confirm redirect to `/admin` showing four KPI cards.

- [ ] **Step 4: Commit**

```bash
git add apps/api/router_admin.py apps/api/templates/admin_kpi.html
git commit -m "feat(admin): KPI dashboard page"
```

---

### Task 5: Users page + actions

**Files:**
- Modify: `apps/api/router_admin.py`
- Create: `apps/api/templates/admin_users.html`

- [ ] **Step 1: Add users routes to router**

Append to `apps/api/router_admin.py`:

```python
@router.get("/users", response_class=HTMLResponse)
def page_users(request: Request, _: None = Depends(require_admin)) -> HTMLResponse:
    with session_scope() as s:
        users = s.execute(
            select(User).order_by(desc(User.created_at)).limit(200)
        ).scalars().all()
    return templates.TemplateResponse(
        "admin_users.html", {"request": request, "users": users}
    )


@router.post("/users/{tg_user_id}/pause")
def action_pause(tg_user_id: int, _: None = Depends(require_admin)) -> RedirectResponse:
    with session_scope() as s:
        user = s.execute(
            select(User).where(User.tg_user_id == tg_user_id)
        ).scalar_one_or_none()
        if user:
            user.state = UserState.PAUSED
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/users/{tg_user_id}/resume")
def action_resume(tg_user_id: int, _: None = Depends(require_admin)) -> RedirectResponse:
    with session_scope() as s:
        user = s.execute(
            select(User).where(User.tg_user_id == tg_user_id)
        ).scalar_one_or_none()
        if user:
            user.state = UserState.ACTIVE
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/users/{tg_user_id}/delete")
def action_delete(tg_user_id: int, _: None = Depends(require_admin)) -> RedirectResponse:
    with session_scope() as s:
        user = s.execute(
            select(User).where(User.tg_user_id == tg_user_id)
        ).scalar_one_or_none()
        if user:
            user.state = UserState.DELETED
    return RedirectResponse(url="/admin/users", status_code=303)
```

- [ ] **Step 2: Create users template**

Create `apps/api/templates/admin_users.html`:

```html
{% extends "admin_base.html" %}
{% block content %}
<h2>Users</h2>
<figure>
<table>
  <thead>
    <tr>
      <th>TG ID</th><th>Username</th><th>State</th>
      <th>Budget (UZS)</th><th>Areas</th><th>Onboarded</th><th>Actions</th>
    </tr>
  </thead>
  <tbody>
  {% for u in users %}
    <tr>
      <td>{{ u.tg_user_id }}</td>
      <td>{{ "@" + u.tg_username if u.tg_username else "—" }}</td>
      <td>
        <span class="badge {% if u.state == 'active' %}badge-ok{% else %}badge-warn{% endif %}">
          {{ u.state }}
        </span>
      </td>
      <td>
        {% if u.budget_min and u.budget_max %}
          {{ "{:,}".format(u.budget_min) }} – {{ "{:,}".format(u.budget_max) }}
        {% else %}—{% endif %}
      </td>
      <td>{{ u.areas | join(", ") if u.areas else "—" }}</td>
      <td>{{ u.onboarded_at.strftime("%Y-%m-%d") if u.onboarded_at else "—" }}</td>
      <td style="white-space:nowrap">
        {% if u.state == "active" %}
          <form method="post" action="/admin/users/{{ u.tg_user_id }}/pause" style="display:inline">
            <button type="submit" class="secondary" style="padding:0.25rem 0.5rem;font-size:0.75rem">Pause</button>
          </form>
        {% elif u.state == "paused" %}
          <form method="post" action="/admin/users/{{ u.tg_user_id }}/resume" style="display:inline">
            <button type="submit" style="padding:0.25rem 0.5rem;font-size:0.75rem">Resume</button>
          </form>
        {% endif %}
        <form method="post" action="/admin/users/{{ u.tg_user_id }}/delete" style="display:inline">
          <button type="submit" class="contrast" style="padding:0.25rem 0.5rem;font-size:0.75rem"
                  onclick="return confirm('Delete user {{ u.tg_user_id }}?')">Delete</button>
        </form>
      </td>
    </tr>
  {% else %}
    <tr><td colspan="7" style="text-align:center">No users yet.</td></tr>
  {% endfor %}
  </tbody>
</table>
</figure>
{% endblock %}
```

- [ ] **Step 3: Commit**

```bash
git add apps/api/router_admin.py apps/api/templates/admin_users.html
git commit -m "feat(admin): users page with pause/resume/delete actions"
```

---

### Task 6: Listings page + suppress action

**Files:**
- Modify: `apps/api/router_admin.py`
- Create: `apps/api/templates/admin_listings.html`

- [ ] **Step 1: Add listings routes to router**

Append to `apps/api/router_admin.py`:

```python
@router.get("/listings", response_class=HTMLResponse)
def page_listings(
    request: Request,
    state: str = Query(default=""),
    _: None = Depends(require_admin),
) -> HTMLResponse:
    with session_scope() as s:
        q = select(Listing).order_by(desc(Listing.created_at)).limit(100)
        if state:
            q = q.where(Listing.state == state)
        listings = s.execute(q).scalars().all()
    return templates.TemplateResponse(
        "admin_listings.html",
        {"request": request, "listings": listings, "state_filter": state},
    )


@router.post("/listings/{listing_id}/suppress")
def action_suppress(listing_id: int, _: None = Depends(require_admin)) -> RedirectResponse:
    with session_scope() as s:
        listing = s.execute(
            select(Listing).where(Listing.id == listing_id)
        ).scalar_one_or_none()
        if listing:
            listing.suppressed = not listing.suppressed
    return RedirectResponse(url="/admin/listings", status_code=303)
```

- [ ] **Step 2: Create listings template**

Create `apps/api/templates/admin_listings.html`:

```html
{% extends "admin_base.html" %}
{% block content %}
<h2>Listings</h2>
<form method="get" style="display:flex;gap:0.5rem;align-items:center;margin-bottom:1rem">
  <select name="state" style="width:auto;margin:0" onchange="this.form.submit()">
    <option value="">All states</option>
    <option value="pending_enrich" {% if state_filter == "pending_enrich" %}selected{% endif %}>pending_enrich</option>
    <option value="active"         {% if state_filter == "active"         %}selected{% endif %}>active</option>
    <option value="dead"           {% if state_filter == "dead"           %}selected{% endif %}>dead</option>
  </select>
  <small>Showing {{ listings|length }} rows</small>
</form>
<figure>
<table>
  <thead>
    <tr>
      <th>ID</th><th>Title</th><th>State</th><th>Risk</th><th>Suppressed</th><th>Source</th><th>Action</th>
    </tr>
  </thead>
  <tbody>
  {% for l in listings %}
    <tr>
      <td>{{ l.id }}</td>
      <td>{{ l.title[:55] }}{% if l.title|length > 55 %}…{% endif %}</td>
      <td><span class="badge {% if l.state == 'active' %}badge-ok{% else %}badge-warn{% endif %}">{{ l.state }}</span></td>
      <td>
        <span class="badge {% if l.risk_score > 3 %}badge-warn{% else %}badge-ok{% endif %}">
          {{ l.risk_score }}
        </span>
      </td>
      <td>{{ "yes" if l.suppressed else "no" }}</td>
      <td><a href="{{ l.source_url }}" target="_blank" rel="noopener">link ↗</a></td>
      <td>
        <form method="post" action="/admin/listings/{{ l.id }}/suppress">
          <button type="submit" class="secondary" style="padding:0.25rem 0.5rem;font-size:0.75rem">
            {{ "Unsuppress" if l.suppressed else "Suppress" }}
          </button>
        </form>
      </td>
    </tr>
  {% else %}
    <tr><td colspan="7" style="text-align:center">No listings.</td></tr>
  {% endfor %}
  </tbody>
</table>
</figure>
{% endblock %}
```

- [ ] **Step 3: Commit**

```bash
git add apps/api/router_admin.py apps/api/templates/admin_listings.html
git commit -m "feat(admin): listings page with state filter and suppress toggle"
```

---

### Task 7: Scrape health page

**Files:**
- Modify: `apps/api/router_admin.py`
- Create: `apps/api/templates/admin_scrape.html`

- [ ] **Step 1: Add scrape health route to router**

Append to `apps/api/router_admin.py`:

```python
@router.get("/scrape", response_class=HTMLResponse)
def page_scrape(request: Request, _: None = Depends(require_admin)) -> HTMLResponse:
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    with session_scope() as s:
        rows = s.execute(
            select(
                ScrapeRunHealth.category,
                func.sum(ScrapeRunHealth.success_count).label("success"),
                func.sum(ScrapeRunHealth.failure_count).label("failure"),
                func.bool_or(ScrapeRunHealth.used_playwright_fallback).label("playwright"),
            )
            .where(ScrapeRunHealth.ts >= cutoff)
            .group_by(ScrapeRunHealth.category)
            .order_by(ScrapeRunHealth.category)
        ).all()
    health = [
        {
            "category": r.category,
            "success": r.success or 0,
            "failure": r.failure or 0,
            "rate": (r.success or 0) / ((r.success or 0) + (r.failure or 0))
                    if ((r.success or 0) + (r.failure or 0)) > 0 else 0.0,
            "playwright": r.playwright,
        }
        for r in rows
    ]
    return templates.TemplateResponse(
        "admin_scrape.html", {"request": request, "health": health}
    )
```

- [ ] **Step 2: Create scrape health template**

Create `apps/api/templates/admin_scrape.html`:

```html
{% extends "admin_base.html" %}
{% block content %}
<h2>Scrape Health <small style="font-size:0.6em;color:var(--pico-muted-color)">(last 24h)</small></h2>
{% if health %}
<figure>
<table>
  <thead>
    <tr><th>Category</th><th>Success</th><th>Failure</th><th>Rate</th><th>Playwright</th></tr>
  </thead>
  <tbody>
  {% for row in health %}
    <tr>
      <td>{{ row.category }}</td>
      <td>{{ row.success }}</td>
      <td>{{ row.failure }}</td>
      <td>
        <span class="badge {% if row.rate >= 0.8 %}badge-ok{% else %}badge-warn{% endif %}">
          {{ "%.1f"|format(row.rate * 100) }}%
        </span>
      </td>
      <td>{{ "yes" if row.playwright else "no" }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
</figure>
{% else %}
<p>No scrape data in the last 24h.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 3: Run linter across new files**

```bash
ruff check apps/api/ --fix
```

Expected: no errors (or auto-fixed whitespace).

- [ ] **Step 4: Final admin smoke test**

With a running stack (`docker compose up -d postgres redis api`), visit each page:
- `http://localhost:8000/admin/login?token=<ADMIN_TOKEN>` → redirects to KPI
- `http://localhost:8000/admin/users` → shows users table
- `http://localhost:8000/admin/listings` → shows listings table
- `http://localhost:8000/admin/scrape` → shows health table
- `http://localhost:8000/admin` with no cookie → 403

- [ ] **Step 5: Commit**

```bash
git add apps/api/router_admin.py apps/api/templates/admin_scrape.html
git commit -m "feat(admin): scrape health page — admin panel complete"
```

---

## Part B — Onboarding Message Cleanup

### Task 9: `_track` and `_flush` helpers (TDD)

**Files:**
- Modify: `apps/bot/handlers/onboarding.py` (helpers only, no handler changes yet)
- Create: `tests/unit/test_onboarding_cleanup.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_onboarding_cleanup.py`:

```python
import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_track_appends_to_empty():
    from apps.bot.handlers.onboarding import _track
    state = AsyncMock()
    state.get_data.return_value = {}
    await _track(state, 42)
    state.update_data.assert_called_once_with(_del_ids=[42])


@pytest.mark.asyncio
async def test_track_appends_to_existing():
    from apps.bot.handlers.onboarding import _track
    state = AsyncMock()
    state.get_data.return_value = {"_del_ids": [1, 2]}
    await _track(state, 3, 4)
    state.update_data.assert_called_once_with(_del_ids=[1, 2, 3, 4])


@pytest.mark.asyncio
async def test_flush_calls_delete_for_each_id():
    from apps.bot.handlers.onboarding import _flush
    state = AsyncMock()
    state.get_data.return_value = {"_del_ids": [10, 20, 30]}
    bot = AsyncMock()
    await _flush(bot, chat_id=999, state=state)
    assert bot.delete_message.call_count == 3
    bot.delete_message.assert_any_call(999, 10)
    bot.delete_message.assert_any_call(999, 20)
    bot.delete_message.assert_any_call(999, 30)
    state.update_data.assert_called_once_with(_del_ids=[])


@pytest.mark.asyncio
async def test_flush_suppresses_delete_errors():
    from apps.bot.handlers.onboarding import _flush
    state = AsyncMock()
    state.get_data.return_value = {"_del_ids": [10]}
    bot = AsyncMock()
    bot.delete_message.side_effect = Exception("message not found")
    await _flush(bot, chat_id=999, state=state)  # must not raise
    state.update_data.assert_called_once_with(_del_ids=[])


@pytest.mark.asyncio
async def test_flush_empty_is_noop():
    from apps.bot.handlers.onboarding import _flush
    state = AsyncMock()
    state.get_data.return_value = {}
    bot = AsyncMock()
    await _flush(bot, chat_id=999, state=state)
    bot.delete_message.assert_not_called()
    state.update_data.assert_called_once_with(_del_ids=[])
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/unit/test_onboarding_cleanup.py -v
```

Expected: ImportError — `_track` and `_flush` not defined yet.

- [ ] **Step 3: Add helpers to `onboarding.py`**

At the top of `apps/bot/handlers/onboarding.py`, add to the existing imports:

```python
from contextlib import suppress
```

Then, after the `log = logging.getLogger(__name__)` line, add the two helpers:

```python
async def _track(state: FSMContext, *msg_ids: int) -> None:
    data = await state.get_data()
    ids = list(data.get("_del_ids", []))
    ids.extend(msg_ids)
    await state.update_data(_del_ids=ids)


async def _flush(bot, chat_id: int, state: FSMContext) -> None:
    data = await state.get_data()
    for mid in data.get("_del_ids", []):
        with suppress(Exception):
            await bot.delete_message(chat_id, mid)
    await state.update_data(_del_ids=[])
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/unit/test_onboarding_cleanup.py -v
```

Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add apps/bot/handlers/onboarding.py tests/unit/test_onboarding_cleanup.py
git commit -m "feat(onboarding): add _track/_flush message cleanup helpers"
```

---

### Task 10: Apply cleanup to welcome + simple callback handlers

Handlers modified in this task: `cb_start`, `cb_search_type`, `cb_gender_pref`, `cb_budget` (button path), `cb_rooms`.

**Pattern for all simple callback handlers:**
1. `await callback.message.delete()` — removes the answered question immediately
2. Transition state
3. Send next question, capture return value
4. `await _track(state, sent.message_id)` — register for future deletion

**Files:**
- Modify: `apps/bot/handlers/onboarding.py:43-103`

- [ ] **Step 1: Replace `cb_start`**

```python
@router.callback_query(lambda c: c.data == kb.CB_START)
async def cb_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.delete()
    await state.set_state(Onboarding.search_type)
    sent = await callback.message.answer(msg.ASK_SEARCH_TYPE, reply_markup=kb.search_type_kb())
    await _track(state, sent.message_id)
    await callback.answer()
```

- [ ] **Step 2: Replace `cb_search_type`**

```python
@router.callback_query(Onboarding.search_type, lambda c: c.data and c.data.startswith(f"{kb.CB_SEARCH_TYPE}:"))
async def cb_search_type(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    await state.update_data(search_type=value)
    await callback.message.delete()
    if value in ("shared_room", "looking_for_roommate"):
        await state.set_state(Onboarding.gender_pref)
        sent = await callback.message.answer(msg.ASK_GENDER_PREF, reply_markup=kb.gender_pref_kb())
    else:
        await state.set_state(Onboarding.budget)
        sent = await callback.message.answer(msg.ASK_BUDGET, reply_markup=kb.budget_kb())
    await _track(state, sent.message_id)
    await callback.answer()
```

- [ ] **Step 3: Replace `cb_gender_pref`**

```python
@router.callback_query(Onboarding.gender_pref, lambda c: c.data and c.data.startswith(f"{kb.CB_GENDER_PREF}:"))
async def cb_gender_pref(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    await state.update_data(gender_pref=value)
    await callback.message.delete()
    await state.set_state(Onboarding.budget)
    sent = await callback.message.answer(msg.ASK_BUDGET, reply_markup=kb.budget_kb())
    await _track(state, sent.message_id)
    await callback.answer()
```

- [ ] **Step 4: Replace `cb_budget`**

```python
@router.callback_query(Onboarding.budget, lambda c: c.data and c.data.startswith(f"{kb.CB_BUDGET}:"))
async def cb_budget(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    await callback.message.delete()
    if parts[1] == "custom":
        await state.set_state(Onboarding.budget_custom)
        sent = await callback.message.answer(msg.ASK_BUDGET_CUSTOM_MAX)
        await _track(state, sent.message_id)
        await callback.answer()
        return
    lo, hi = int(parts[1]), int(parts[2])
    await state.update_data(budget_min=lo, budget_max=hi)
    await state.set_state(Onboarding.rooms)
    sent = await callback.message.answer(msg.ASK_ROOMS, reply_markup=kb.rooms_kb())
    await _track(state, sent.message_id)
    await callback.answer()
```

- [ ] **Step 5: Replace `cb_rooms`**

```python
@router.callback_query(lambda c: c.data and c.data.startswith(f"{kb.CB_ROOMS}:"))
async def cb_rooms(callback: CallbackQuery, state: FSMContext) -> None:
    val = int(callback.data.split(":")[1])
    await state.update_data(rooms=val if val > 0 else None)
    await callback.message.delete()
    await state.set_state(Onboarding.areas)
    await state.update_data(areas=[])
    sent = await callback.message.answer(msg.ASK_AREAS, reply_markup=kb.areas_kb([]))
    await _track(state, sent.message_id)
    await callback.answer()
```

- [ ] **Step 6: Commit**

```bash
git add apps/bot/handlers/onboarding.py
git commit -m "feat(onboarding): delete answered questions in welcome + budget + rooms flow"
```

---

### Task 11: Apply cleanup to multi-select handlers (areas + dealbreakers)

Multi-select steps edit the keyboard in place on toggles — no changes needed for toggle handlers. Only the "Done" handlers and the "custom area" sub-flow need changes.

**Files:**
- Modify: `apps/bot/handlers/onboarding.py` — `cb_area_custom`, `msg_custom_area`, `cb_area_done`, `cb_dealbreakers_done`

- [ ] **Step 1: Replace `cb_area_custom`**

Track the "please type area" prompt so it gets swept when the user submits:

```python
@router.callback_query(Onboarding.areas, lambda c: c.data == kb.CB_AREA_CUSTOM)
async def cb_area_custom(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(_awaiting_custom_area=True)
    sent = await callback.message.answer(msg.ASK_CUSTOM_AREA)
    await _track(state, sent.message_id)
    await callback.answer()
```

- [ ] **Step 2: Replace `msg_custom_area`**

Delete user's text and flush all tracked messages (the areas keyboard + the "please type" prompt), then re-send the updated keyboard:

```python
@router.message(Onboarding.areas)
async def msg_custom_area(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("_awaiting_custom_area"):
        return
    await message.delete()
    await _flush(message.bot, message.chat.id, state)
    selected = list(data.get("areas", []))
    selected.append(message.text.strip())
    await state.update_data(areas=selected, _awaiting_custom_area=False)
    sent = await message.answer(
        f"Добавлен: «{message.text.strip()}»",
        reply_markup=kb.areas_kb(selected),
    )
    await _track(state, sent.message_id)
```

- [ ] **Step 3: Replace `cb_area_done`**

```python
@router.callback_query(Onboarding.areas, lambda c: c.data == kb.CB_AREA_DONE)
async def cb_area_done(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("areas"):
        await callback.answer("Выбери хотя бы один район", show_alert=True)
        return
    await callback.message.delete()
    await _flush(callback.message.bot, callback.message.chat.id, state)
    await state.set_state(Onboarding.move_in)
    sent = await callback.message.answer(msg.ASK_MOVE_IN, reply_markup=kb.move_in_kb())
    await _track(state, sent.message_id)
    await callback.answer()
```

- [ ] **Step 4: Replace `cb_dealbreakers_done`**

```python
@router.callback_query(Onboarding.dealbreakers, lambda c: c.data == kb.CB_DB_DONE)
async def cb_dealbreakers_done(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.delete()
    await _flush(callback.message.bot, callback.message.chat.id, state)
    await state.set_state(Onboarding.agent_filter)
    sent = await callback.message.answer(msg.ASK_AGENT_FILTER, reply_markup=kb.agent_filter_kb())
    await _track(state, sent.message_id)
    await callback.answer()
```

- [ ] **Step 5: Commit**

```bash
git add apps/bot/handlers/onboarding.py
git commit -m "feat(onboarding): delete answered questions in areas + dealbreakers multi-select"
```

---

### Task 12: Apply cleanup to remaining callback handlers

Handlers: `cb_move_in`, `cb_commute_skip`, `cb_commute_minutes`, `cb_commute_mode`, `cb_agent_filter`, `cb_axis_priority`, `cb_free_text_wall`, `cb_free_text_skip`.

**Files:**
- Modify: `apps/bot/handlers/onboarding.py:192-411`

- [ ] **Step 1: Replace `cb_move_in`**

```python
@router.callback_query(Onboarding.move_in, lambda c: c.data and c.data.startswith(f"{kb.CB_MOVE_IN}:"))
async def cb_move_in(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    await state.update_data(move_in_window=value)
    await callback.message.delete()
    await state.set_state(Onboarding.commute_origin)
    sent = await callback.message.answer(msg.ASK_COMMUTE_ORIGIN, reply_markup=kb.commute_skip_kb())
    await _track(state, sent.message_id)
    await callback.answer()
```

- [ ] **Step 2: Replace `cb_commute_skip`**

```python
@router.callback_query(Onboarding.commute_origin, lambda c: c.data == kb.CB_COMMUTE_SKIP)
async def cb_commute_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(commute_origin=None)
    await callback.message.delete()
    await _flush(callback.message.bot, callback.message.chat.id, state)
    await state.set_state(Onboarding.dealbreakers)
    await state.update_data(dealbreakers=[])
    sent = await callback.message.answer(msg.ASK_DEALBREAKERS, reply_markup=kb.dealbreakers_kb([]))
    await _track(state, sent.message_id)
    await callback.answer()
```

- [ ] **Step 3: Replace `cb_commute_minutes`**

```python
@router.callback_query(Onboarding.commute_minutes, lambda c: c.data and c.data.startswith(f"{kb.CB_COMMUTE_MINUTES}:"))
async def cb_commute_minutes(callback: CallbackQuery, state: FSMContext) -> None:
    val = int(callback.data.split(":")[1])
    await state.update_data(commute_max_minutes=val)
    await callback.message.delete()
    await state.set_state(Onboarding.commute_mode)
    sent = await callback.message.answer(msg.ASK_COMMUTE_MODE, reply_markup=kb.commute_mode_kb())
    await _track(state, sent.message_id)
    await callback.answer()
```

- [ ] **Step 4: Replace `cb_commute_mode`**

```python
@router.callback_query(Onboarding.commute_mode, lambda c: c.data and c.data.startswith(f"{kb.CB_COMMUTE_MODE}:"))
async def cb_commute_mode(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    await state.update_data(commute_mode=value)
    await callback.message.delete()
    await _flush(callback.message.bot, callback.message.chat.id, state)
    await state.set_state(Onboarding.dealbreakers)
    await state.update_data(dealbreakers=[])
    sent = await callback.message.answer(msg.ASK_DEALBREAKERS, reply_markup=kb.dealbreakers_kb([]))
    await _track(state, sent.message_id)
    await callback.answer()
```

- [ ] **Step 5: Replace `cb_agent_filter`**

```python
@router.callback_query(Onboarding.agent_filter, lambda c: c.data and c.data.startswith(f"{kb.CB_AGENT_FILTER}:"))
async def cb_agent_filter(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    await state.update_data(agent_filter=value)
    data = await state.get_data()

    axes: list[str] = ["budget"]
    axis_priority: dict[str, str] = {}

    areas = data.get("areas", [])
    if len(areas) > 1:
        axes.append("area")
    else:
        axis_priority["area"] = "MUST"

    if data.get("commute_origin"):
        axes.append("commute")

    if data.get("rooms") is not None:
        axes.append("rooms")

    await state.update_data(axis_priority=axis_priority, pending_axes=axes)
    await callback.message.delete()
    await state.set_state(Onboarding.axis_priority)
    first_axis = axes[0]
    label = AXIS_LABELS[first_axis]
    sent = await callback.message.answer(
        msg.ASK_AXIS_PRIORITY.format(axis=label),
        reply_markup=kb.axis_priority_kb(first_axis),
    )
    await _track(state, sent.message_id)
    await callback.answer()
```

- [ ] **Step 6: Replace `cb_axis_priority`**

```python
@router.callback_query(Onboarding.axis_priority, lambda c: c.data and c.data.startswith(f"{kb.CB_AXIS}:"))
async def cb_axis_priority(callback: CallbackQuery, state: FSMContext) -> None:
    _, priority, axis_key = callback.data.split(":")
    data = await state.get_data()
    axis_priority: dict = dict(data.get("axis_priority", {}))
    axis_priority[axis_key] = priority.upper()
    pending: list[str] = [a for a in data.get("pending_axes", []) if a != axis_key]
    await state.update_data(axis_priority=axis_priority, pending_axes=pending)
    await callback.message.delete()
    if pending:
        next_axis = pending[0]
        label = AXIS_LABELS[next_axis]
        sent = await callback.message.answer(
            msg.ASK_AXIS_PRIORITY.format(axis=label),
            reply_markup=kb.axis_priority_kb(next_axis),
        )
        await _track(state, sent.message_id)
    else:
        await state.set_state(Onboarding.free_text_wall)
        sent = await callback.message.answer(msg.FREE_TEXT_WALL, reply_markup=kb.free_text_wall_kb())
        await _track(state, sent.message_id)
    await callback.answer()
```

- [ ] **Step 7: Replace `cb_free_text_wall`**

```python
@router.callback_query(Onboarding.free_text_wall, lambda c: c.data and c.data.startswith(f"{kb.CB_FREE_TEXT_WALL}:"))
async def cb_free_text_wall(callback: CallbackQuery, state: FSMContext) -> None:
    choice = callback.data.split(":")[1]
    await callback.message.delete()
    if choice == "skip":
        await _trigger_done(callback.message, callback.from_user, state)
    else:
        await state.set_state(Onboarding.free_text_1)
        sent = await callback.message.answer(msg.FREE_TEXT_1, reply_markup=kb.free_text_skip_kb())
        await _track(state, sent.message_id)
    await callback.answer()
```

- [ ] **Step 8: Replace `cb_free_text_skip`**

```python
@router.callback_query(StateFilter(Onboarding.free_text_1, Onboarding.free_text_2, Onboarding.free_text_3), lambda c: c.data == kb.CB_FREE_TEXT_SKIP)
async def cb_free_text_skip(callback: CallbackQuery, state: FSMContext) -> None:
    current = await state.get_state()
    await callback.message.delete()
    if current == Onboarding.free_text_1:
        await state.set_state(Onboarding.free_text_2)
        sent = await callback.message.answer(msg.FREE_TEXT_2, reply_markup=kb.free_text_skip_kb())
        await _track(state, sent.message_id)
    elif current == Onboarding.free_text_2:
        await state.set_state(Onboarding.free_text_3)
        sent = await callback.message.answer(msg.FREE_TEXT_3, reply_markup=kb.free_text_skip_kb())
        await _track(state, sent.message_id)
    else:
        await _trigger_done(callback.message, callback.from_user, state)
    await callback.answer()
```

- [ ] **Step 9: Commit**

```bash
git add apps/bot/handlers/onboarding.py
git commit -m "feat(onboarding): delete answered questions — commute, axes, free-text callbacks"
```

---

### Task 13: Apply cleanup to all text handlers + final lint

Text handlers: `msg_budget_custom`, `msg_commute_origin`, `msg_free_text_1`, `msg_free_text_2`, `msg_free_text_3`.

**Pattern for text handlers:**
1. `await message.delete()` — remove user's typed message immediately
2. `await _flush(message.bot, message.chat.id, state)` — remove bot's preceding prompt(s)
3. Transition state
4. Send next question, track it

**Files:**
- Modify: `apps/bot/handlers/onboarding.py:106-395`

- [ ] **Step 1: Replace `msg_budget_custom`**

```python
@router.message(Onboarding.budget_custom)
async def msg_budget_custom(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    step = data.get("_budget_step", "max")
    try:
        val = int(message.text.replace(" ", "").replace(",", ""))
    except ValueError:
        await message.delete()
        sent = await message.answer("Введи число, например: 2500000")
        await _track(state, sent.message_id)
        return
    await message.delete()
    await _flush(message.bot, message.chat.id, state)
    if step == "max":
        await state.update_data(budget_max=val, _budget_step="min")
        sent = await message.answer(msg.ASK_BUDGET_CUSTOM_MIN)
        await _track(state, sent.message_id)
    else:
        await state.update_data(budget_min=val)
        await state.set_state(Onboarding.rooms)
        sent = await message.answer(msg.ASK_ROOMS, reply_markup=kb.rooms_kb())
        await _track(state, sent.message_id)
```

- [ ] **Step 2: Replace `msg_commute_origin`**

```python
@router.message(Onboarding.commute_origin)
async def msg_commute_origin(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    await message.delete()
    await _flush(message.bot, message.chat.id, state)
    result = await _geocode_async(text)
    if result.lat is None:
        sent = await message.answer(msg.GEOCODE_FAILED, reply_markup=kb.commute_skip_kb())
        await _track(state, sent.message_id)
        return
    await state.update_data(
        commute_origin=text,
        commute_origin_lat=result.lat,
        commute_origin_lng=result.lng,
    )
    await state.set_state(Onboarding.commute_minutes)
    sent = await message.answer(msg.ASK_COMMUTE_MINUTES, reply_markup=kb.commute_minutes_kb())
    await _track(state, sent.message_id)
```

- [ ] **Step 3: Replace `msg_free_text_1`**

```python
@router.message(Onboarding.free_text_1)
async def msg_free_text_1(message: Message, state: FSMContext) -> None:
    await state.update_data(tradeoff_hint_text=message.text.strip())
    await message.delete()
    await _flush(message.bot, message.chat.id, state)
    await state.set_state(Onboarding.free_text_2)
    sent = await message.answer(msg.FREE_TEXT_2, reply_markup=kb.free_text_skip_kb())
    await _track(state, sent.message_id)
```

- [ ] **Step 4: Replace `msg_free_text_2`**

```python
@router.message(Onboarding.free_text_2)
async def msg_free_text_2(message: Message, state: FSMContext) -> None:
    await state.update_data(unacceptable_text=message.text.strip())
    await message.delete()
    await _flush(message.bot, message.chat.id, state)
    await state.set_state(Onboarding.free_text_3)
    sent = await message.answer(msg.FREE_TEXT_3, reply_markup=kb.free_text_skip_kb())
    await _track(state, sent.message_id)
```

- [ ] **Step 5: Replace `msg_free_text_3`**

```python
@router.message(Onboarding.free_text_3)
async def msg_free_text_3(message: Message, state: FSMContext) -> None:
    await state.update_data(instant_reject_text=message.text.strip())
    await message.delete()
    await _flush(message.bot, message.chat.id, state)
    await _trigger_done(message, message.from_user, state)
```

- [ ] **Step 6: Run full test suite**

```bash
pytest tests/unit/ -v
```

Expected: all tests pass, including the 5 new cleanup tests.

- [ ] **Step 7: Run linter**

```bash
ruff check apps/bot/handlers/onboarding.py --fix
```

Expected: no errors.

- [ ] **Step 8: Final commit**

```bash
git add apps/bot/handlers/onboarding.py
git commit -m "feat(onboarding): delete user text replies — cleanup complete"
```
