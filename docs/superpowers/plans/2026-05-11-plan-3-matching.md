# Scout Plan 3: Matching, Digest & Instant Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `matches` table, push-from-enrich fanout, hard filters + 7-component scoring, templated reasons, daily 09:00 Tashkent digest, instant alerts (≤3/day, quiet hours), cold-start stratified picks, and top-1% threshold recompute. Users receive real digests with working buttons; Plan 4 layers ML feedback on top.

**Architecture:** New module `apps/shared/matching/` (score, reasons, coldstart, config). New `apps/shared/telegram_send.py` is a sync wrapper around aiogram for Celery workers. Two new Celery task modules (`match.py`, `digest.py`); one-line hook into `enrich.py`. Bot gains stub callback handlers (event-log only) and two new inline keyboards.

**Tech Stack:** SQLAlchemy 2 + pgvector, Celery 5, aiogram 3, FastAPI (not touched), pytest + testcontainers, asyncio.run for sync→async bridge.

**Spec:** `docs/superpowers/specs/2026-05-11-plan-3-matching-design.md`

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `apps/shared/enums.py` | modify | add `MatchState`, `DeliveredVia` StrEnums |
| `apps/shared/models.py` | modify | add `Match` SQLAlchemy model |
| `alembic/versions/<hash>_add_matches.py` | create | migration |
| `apps/shared/matching/__init__.py` | create | re-exports |
| `apps/shared/matching/config.py` | create | weights + thresholds (env-overridable) |
| `apps/shared/matching/reasons.py` | create | templated reason builders |
| `apps/shared/matching/coldstart.py` | create | `is_cold_start()`, `stratified_pick()` |
| `apps/shared/matching/filters.py` | create | hard-filter helpers (`sql_filter_candidates`, `python_filter_pass`) |
| `apps/shared/matching/score.py` | create | scoring formula |
| `apps/shared/telegram_send.py` | create | sync aiogram Bot wrapper for workers |
| `apps/bot/keyboards.py` | modify | `match_actions_kb`, `dislike_reasons_kb` |
| `apps/bot/messages.py` | modify | reason RU strings, digest header text |
| `apps/bot/handlers/match_callbacks.py` | create | stub 👍/👎/📞 handlers |
| `apps/bot/main.py` | modify | import + register match_callbacks router |
| `apps/workers/tasks/match.py` | create | `match_fanout_listing`, `match_alert_instant`, `match_threshold_recompute`, `match_cleanup_dead` |
| `apps/workers/tasks/digest.py` | create | `digest_send_daily`, `digest_send_for_user` |
| `apps/workers/tasks/enrich.py` | modify | dispatch `match_fanout_listing.delay()` |
| `apps/workers/celery_app.py` | modify | register new tasks + 3 beat entries |
| `tests/unit/test_match_model.py` | create | Match model + UNIQUE constraint |
| `tests/unit/test_matching_config.py` | create | env override behavior |
| `tests/unit/test_reasons.py` | create | reason string formatting |
| `tests/unit/test_coldstart.py` | create | gate + stratifier |
| `tests/unit/test_filters.py` | create | hard filter truth table |
| `tests/unit/test_scoring.py` | create | score components + final formula |
| `tests/unit/test_telegram_send.py` | create | format_match_text + helpers |
| `tests/unit/test_match_keyboards.py` | create | match_actions_kb + dislike_reasons_kb |
| `tests/unit/test_match_callbacks.py` | create | callback handlers emit events |
| `tests/unit/test_match_fanout.py` | create | end-to-end fanout with DB |
| `tests/unit/test_digest_task.py` | create | digest picker (cold-start + normal) |
| `tests/unit/test_threshold_recompute.py` | create | personal / global / bootstrap paths |
| `tests/unit/test_match_cleanup.py` | create | dead listing → match.state='dead' |
| `tests/unit/test_celery_beat_schedule.py` | modify or create | verifies new beat entries exist |

---

## Task 1: Enums + Match model + migration

**Files:**
- Modify: `apps/shared/enums.py`
- Modify: `apps/shared/models.py`
- Create: `tests/unit/test_match_model.py`
- Create: `alembic/versions/<hash>_add_matches.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_match_model.py`:

```python
import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from apps.shared.enums import MatchState, DeliveredVia
from apps.shared.models import Base, Match


def test_match_table_exists(engine):
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    assert "matches" in insp.get_table_names()


def test_match_create_minimal(engine, db_session):
    Base.metadata.create_all(engine)
    m = Match(user_id=1, listing_id=1, score=0.5, reasons=["💰 test"])
    db_session.add(m)
    db_session.flush()
    assert m.id is not None
    assert m.state == "pending"
    assert m.delivered_via is None


def test_match_unique_user_listing(engine, db_session):
    Base.metadata.create_all(engine)
    db_session.add(Match(user_id=2, listing_id=2, score=0.5, reasons=[]))
    db_session.flush()
    db_session.add(Match(user_id=2, listing_id=2, score=0.6, reasons=[]))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_match_state_enum_values():
    assert MatchState.PENDING == "pending"
    assert MatchState.SENT == "sent"
    assert MatchState.LIKED == "liked"
    assert MatchState.DISLIKED == "disliked"
    assert MatchState.CONTACTED == "contacted"
    assert MatchState.RENTED == "rented"
    assert MatchState.DEAD == "dead"


def test_delivered_via_enum_values():
    assert DeliveredVia.DIGEST == "digest"
    assert DeliveredVia.INSTANT == "instant"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_match_model.py -v`
Expected: ImportError (`MatchState` / `DeliveredVia` / `Match` not found).

- [ ] **Step 3: Add enums to `apps/shared/enums.py`**

Append to `apps/shared/enums.py`:

```python
class MatchState(StrEnum):
    PENDING   = "pending"
    SENT      = "sent"
    LIKED     = "liked"
    DISLIKED  = "disliked"
    CONTACTED = "contacted"
    RENTED    = "rented"
    DEAD      = "dead"


class DeliveredVia(StrEnum):
    DIGEST  = "digest"
    INSTANT = "instant"
```

- [ ] **Step 4: Add Match model to `apps/shared/models.py`**

Append to the imports at the top of `apps/shared/models.py` (extend the existing import from `enums`):

```python
from apps.shared.enums import (  # noqa: F401
    BathroomType,
    DeliveredVia,
    GenderConstraint,
    ListingState,
    MatchState,
    OlxCategory,
    PosterRole,
    SearchType,
    UserState,
)
```

Append the model after the `Event` class:

```python
class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    listing_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    score: Mapped[float] = mapped_column(Float, nullable=False)
    reasons: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, nullable=False)

    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default=MatchState.PENDING, index=True
    )
    delivered_via: Mapped[str | None] = mapped_column(String(8))
    dislike_reason: Mapped[str | None] = mapped_column(String(32))

    liked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disliked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    chase_48h_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    chase_48h_done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    chase_5d_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    chase_5d_done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "listing_id", name="uq_matches_user_listing"),
        Index("ix_matches_user_state_score", "user_id", "state", "score"),
        Index(
            "ix_matches_user_delivered",
            "user_id",
            "delivered_via",
            "created_at",
        ),
        Index(
            "ix_matches_pending_score",
            "state",
            "score",
            postgresql_where="state = 'pending'",
        ),
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_match_model.py -v`
Expected: 5 tests PASS.

- [ ] **Step 6: Generate Alembic migration**

Run: `uv run alembic revision --autogenerate -m "add matches table"`
Expected: a new file `alembic/versions/<hash>_add_matches_table.py` is created. Inspect it — the `upgrade()` should create the `matches` table with the four indexes from `__table_args__`. The `downgrade()` should drop it.

If autogenerate produces extra noise (e.g., index renames on unrelated tables), edit the migration to keep only the `matches` create/drop ops.

- [ ] **Step 7: Apply the migration**

Run: `docker compose up -d postgres && uv run alembic upgrade head`
Expected: migration applies cleanly. `psql ... -c "\d matches"` shows the table with the four indexes.

- [ ] **Step 8: Commit**

```bash
git add apps/shared/enums.py apps/shared/models.py alembic/versions/ tests/unit/test_match_model.py
git commit -m "feat(matching): add Match model + matches table migration"
```

---

## Task 2: Matching config module

**Files:**
- Create: `apps/shared/matching/__init__.py`
- Create: `apps/shared/matching/config.py`
- Create: `tests/unit/test_matching_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_matching_config.py`:

```python
import importlib
import os

import pytest


def test_default_weights_sum_reasonable():
    from apps.shared.matching import config as c
    pos = c.W_COSINE + c.W_BUDGET + c.W_COMMUTE + c.W_FRESHNESS + c.W_SOURCE_REP + c.W_AXIS_BONUS
    assert 0.9 <= pos <= 1.1, f"positive weights should sum near 1.0, got {pos}"


def test_insert_threshold_in_unit_range():
    from apps.shared.matching import config as c
    assert 0.0 < c.INSERT_THRESHOLD < 1.0


def test_quiet_hours_bound():
    from apps.shared.matching import config as c
    assert 0 <= c.QUIET_HOURS_END < c.QUIET_HOURS_START <= 24


def test_env_override(monkeypatch):
    monkeypatch.setenv("MATCHING_W_COSINE", "0.55")
    import apps.shared.matching.config as cfg_mod
    importlib.reload(cfg_mod)
    try:
        assert cfg_mod.W_COSINE == pytest.approx(0.55)
    finally:
        monkeypatch.delenv("MATCHING_W_COSINE")
        importlib.reload(cfg_mod)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_matching_config.py -v`
Expected: ModuleNotFoundError (`apps.shared.matching.config`).

- [ ] **Step 3: Create the module**

Create `apps/shared/matching/__init__.py` (empty file).

Create `apps/shared/matching/config.py`:

```python
"""Matching scoring weights, thresholds, and operational gates.

All values can be overridden at process startup via env vars with the
``MATCHING_`` prefix (e.g. ``MATCHING_W_COSINE=0.55``).
"""

import os


def _f(name: str, default: float) -> float:
    raw = os.getenv(f"MATCHING_{name}")
    return float(raw) if raw is not None else default


def _i(name: str, default: int) -> int:
    raw = os.getenv(f"MATCHING_{name}")
    return int(raw) if raw is not None else default


W_COSINE      = _f("W_COSINE",      0.40)
W_BUDGET      = _f("W_BUDGET",      0.20)
W_COMMUTE     = _f("W_COMMUTE",     0.15)
W_FRESHNESS   = _f("W_FRESHNESS",   0.10)
W_SOURCE_REP  = _f("W_SOURCE_REP",  0.05)
W_AXIS_BONUS  = _f("W_AXIS_BONUS",  0.07)
W_RISK        = _f("W_RISK",        0.10)

INSERT_THRESHOLD          = _f("INSERT_THRESHOLD",          0.20)
COLD_START_REACTIONS      = _i("COLD_START_REACTIONS",      10)
INSTANT_DAILY_CAP         = _i("INSTANT_DAILY_CAP",         3)
QUIET_HOURS_START         = _i("QUIET_HOURS_START",         22)
QUIET_HOURS_END           = _i("QUIET_HOURS_END",           8)
GLOBAL_TOP1PCT_BOOTSTRAP  = _f("GLOBAL_TOP1PCT_BOOTSTRAP",  0.75)
THRESHOLD_MIN_PERSONAL    = _i("THRESHOLD_MIN_PERSONAL",    50)
THRESHOLD_MIN_GLOBAL      = _i("THRESHOLD_MIN_GLOBAL",      200)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_matching_config.py -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/shared/matching/__init__.py apps/shared/matching/config.py tests/unit/test_matching_config.py
git commit -m "feat(matching): add config module with env overrides"
```

---

## Task 3: Templated reasons

**Files:**
- Create: `apps/shared/matching/reasons.py`
- Create: `tests/unit/test_reasons.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_reasons.py`:

```python
from dataclasses import dataclass
from datetime import datetime, timedelta, UTC

from apps.shared.enums import PosterRole
from apps.shared.matching.reasons import (
    build_reasons,
    format_uzs,
    age_human,
    rooms_str,
    tuman_ru,
    ScoreComponents,
)


def _listing(**kw):
    @dataclass
    class L:
        price_uzs: int = 1_400_000
        rooms: int | None = 2
        area: str | None = "Yunusabad"
        poster_role: str | None = PosterRole.OWNER
        agent_fee_text: str | None = None
        posted_at: datetime | None = None
        is_furnished: bool | None = None
        risk_flags: dict | None = None
        summary_one_line: str | None = None
    return L(**kw)


def _user(**kw):
    @dataclass
    class U:
        budget_min: int = 1_000_000
        budget_max: int = 1_500_000
    return U(**kw)


def test_format_uzs_thousands_separator():
    assert format_uzs(1_400_000) == "1 400 000 UZS"


def test_age_human_buckets():
    now = datetime.now(UTC)
    assert "мин назад" in age_human(now - timedelta(minutes=12))
    assert "ч назад" in age_human(now - timedelta(hours=3))
    assert age_human(now - timedelta(hours=20)) == "вчера" or "ч назад" in age_human(now - timedelta(hours=20))
    assert "дн назад" in age_human(now - timedelta(days=3))


def test_rooms_str():
    assert rooms_str(2) == "2-комн."
    assert rooms_str(None) == "квартира"
    assert rooms_str(4) == "4-комн."


def test_tuman_ru_passthrough():
    assert tuman_ru("Yunusabad") == "Юнусабад"
    assert tuman_ru("Chilanzar") == "Чиланзар"


def test_reasons_under_budget():
    posted = datetime.now(UTC) - timedelta(minutes=30)
    r = build_reasons(
        _user(),
        _listing(price_uzs=1_400_000, posted_at=posted),
        ScoreComponents(cosine=0.7),
    )
    assert any("в твоём бюджете" in s for s in r)
    assert any("📍 Юнусабад" in s for s in r)
    assert any("👤 хозяин" in s for s in r)


def test_reasons_over_budget():
    posted = datetime.now(UTC) - timedelta(hours=2)
    r = build_reasons(
        _user(budget_max=1_500_000),
        _listing(price_uzs=1_800_000, posted_at=posted),
        ScoreComponents(),
    )
    assert any("выше бюджета" in s for s in r)


def test_reasons_agent_with_fee():
    r = build_reasons(
        _user(),
        _listing(poster_role=PosterRole.AGENT, agent_fee_text="50%"),
        ScoreComponents(),
    )
    assert any("🏢 агент · комиссия 50%" in s for s in r)


def test_reasons_agent_without_fee():
    r = build_reasons(
        _user(),
        _listing(poster_role=PosterRole.AGENT),
        ScoreComponents(),
    )
    assert any(s == "🏢 агент" for s in r)


def test_reasons_includes_commute_when_known():
    r = build_reasons(
        _user(),
        _listing(),
        ScoreComponents(commute_minutes=18),
    )
    assert any("🚇 18 мин до работы" in s for s in r)


def test_reasons_omits_commute_when_unknown():
    r = build_reasons(_user(), _listing(), ScoreComponents(commute_minutes=None))
    assert not any("🚇" in s for s in r)


def test_reasons_risk_warnings():
    r = build_reasons(
        _user(),
        _listing(risk_flags={"phash_collision": True, "price_outlier": True}),
        ScoreComponents(),
    )
    assert any("возможно повторное фото" in s for s in r)
    assert any("необычно низкая цена" in s for s in r)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_reasons.py -v`
Expected: ImportError.

- [ ] **Step 3: Create the reasons module**

Create `apps/shared/matching/reasons.py`:

```python
"""Templated reason strings for match messages.

Reasons are computed once at fanout time and stored on the Match row so
the user always sees what the listing looked like *then*, not now.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from apps.shared.enums import PosterRole


@dataclass
class ScoreComponents:
    """Carrier for facts the reason builder needs but the listing alone
    doesn't expose (e.g. routing result)."""

    cosine: float | None = None
    budget_score: float | None = None
    commute_minutes: int | None = None
    freshness: float | None = None
    source_rep: float | None = None
    axis_bonus: float | None = None
    risk_penalty: int = 0


TUMAN_RU = {
    "Bektemir": "Бектемир",
    "Chilanzar": "Чиланзар",
    "Mirobod": "Мирабад",
    "Mirzo Ulugbek": "Мирзо-Улугбек",
    "Sergeli": "Сергели",
    "Shaykhantakhur": "Шайхантахур",
    "Uchtepa": "Учтепа",
    "Yakkasaray": "Яккасарай",
    "Yashnobod": "Яшнабад",
    "Yunusabad": "Юнусабад",
    "Almazar": "Алмазар",
    "Yangihayot": "Янгихаёт",
}


def format_uzs(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " UZS"


def rooms_str(rooms: int | None) -> str:
    if rooms is None:
        return "квартира"
    return f"{rooms}-комн."


def tuman_ru(area: str | None) -> str:
    if area is None:
        return ""
    return TUMAN_RU.get(area, area)


def age_human(posted_at: datetime | None) -> str:
    if posted_at is None:
        return "недавно"
    now = datetime.now(timezone.utc)
    delta = now - posted_at
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"{max(minutes, 1)} мин назад"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} ч назад"
    days = hours // 24
    if days == 1:
        return "вчера"
    return f"{days} дн назад"


def build_reasons(user, listing, components: ScoreComponents) -> list[str]:
    out: list[str] = []

    if listing.price_uzs is not None:
        budget_max = getattr(user, "budget_max", None) or 0
        suffix = "в твоём бюджете" if listing.price_uzs <= budget_max else "выше бюджета"
        out.append(f"💰 {format_uzs(listing.price_uzs)} · {suffix}")

    if components.commute_minutes is not None:
        out.append(f"🚇 {components.commute_minutes} мин до работы")

    out.append(f"🆕 {age_human(listing.posted_at)}")

    if listing.area:
        out.append(f"📍 {tuman_ru(listing.area)}")

    role = listing.poster_role
    if role == PosterRole.OWNER:
        out.append("👤 хозяин")
    elif role == PosterRole.AGENT:
        if listing.agent_fee_text:
            out.append(f"🏢 агент · комиссия {listing.agent_fee_text}")
        else:
            out.append("🏢 агент")

    flags = listing.risk_flags or {}
    if flags.get("phash_collision"):
        out.append("⚠️ возможно повторное фото")
    if flags.get("price_outlier"):
        out.append("⚠️ необычно низкая цена")

    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_reasons.py -v`
Expected: 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/shared/matching/reasons.py tests/unit/test_reasons.py
git commit -m "feat(matching): templated reason builders"
```

---

## Task 4: Cold-start gate + stratified picker

**Files:**
- Create: `apps/shared/matching/coldstart.py`
- Create: `tests/unit/test_coldstart.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_coldstart.py`:

```python
from dataclasses import dataclass

import pytest

from apps.shared.enums import MatchState, UserState
from apps.shared.matching.coldstart import is_cold_start, stratified_pick
from apps.shared.matching.config import COLD_START_REACTIONS
from apps.shared.models import Base, Match, User


@dataclass
class _Pick:
    """Stand-in for a Match row in stratifier tests."""

    id: int
    score: float
    price_uzs: int
    area: str
    is_furnished: bool | None
    listing_id: int = 0

    def __post_init__(self):
        if self.listing_id == 0:
            self.listing_id = self.id


def test_is_cold_start_true_when_zero_reactions(engine, db_session):
    Base.metadata.create_all(engine)
    u = User(tg_user_id=100, state=UserState.ACTIVE)
    db_session.add(u)
    db_session.flush()
    assert is_cold_start(db_session, u) is True


def test_is_cold_start_false_when_threshold_met(engine, db_session):
    Base.metadata.create_all(engine)
    u = User(tg_user_id=101, state=UserState.ACTIVE)
    db_session.add(u)
    db_session.flush()
    for i in range(COLD_START_REACTIONS):
        db_session.add(Match(
            user_id=u.id, listing_id=1000 + i,
            score=0.5, reasons=[], state=MatchState.LIKED,
        ))
    db_session.flush()
    assert is_cold_start(db_session, u) is False


def test_is_cold_start_counts_disliked_and_contacted(engine, db_session):
    Base.metadata.create_all(engine)
    u = User(tg_user_id=102, state=UserState.ACTIVE)
    db_session.add(u)
    db_session.flush()
    states = [MatchState.LIKED] * 4 + [MatchState.DISLIKED] * 4 + [MatchState.CONTACTED] * 2
    for i, st in enumerate(states):
        db_session.add(Match(
            user_id=u.id, listing_id=2000 + i,
            score=0.5, reasons=[], state=st,
        ))
    db_session.flush()
    assert is_cold_start(db_session, u) is False


def test_is_cold_start_ignores_pending_and_sent(engine, db_session):
    Base.metadata.create_all(engine)
    u = User(tg_user_id=103, state=UserState.ACTIVE)
    db_session.add(u)
    db_session.flush()
    for i in range(20):
        db_session.add(Match(
            user_id=u.id, listing_id=3000 + i,
            score=0.5, reasons=[], state=MatchState.SENT,
        ))
    db_session.flush()
    assert is_cold_start(db_session, u) is True


@dataclass
class _User:
    areas: list[str]


def _pool() -> list[_Pick]:
    return [
        _Pick(id=1,  score=0.9, price_uzs=1_000_000, area="A", is_furnished=True),
        _Pick(id=2,  score=0.88, price_uzs=1_100_000, area="A", is_furnished=True),
        _Pick(id=3,  score=0.86, price_uzs=1_200_000, area="A", is_furnished=True),
        _Pick(id=4,  score=0.85, price_uzs=1_300_000, area="B", is_furnished=False),
        _Pick(id=5,  score=0.80, price_uzs=1_400_000, area="B", is_furnished=False),
        _Pick(id=6,  score=0.78, price_uzs=1_500_000, area="C", is_furnished=False),
        _Pick(id=7,  score=0.70, price_uzs=1_700_000, area="C", is_furnished=True),
        _Pick(id=8,  score=0.60, price_uzs=2_000_000, area="D", is_furnished=False),
        _Pick(id=9,  score=0.55, price_uzs=2_200_000, area="D", is_furnished=True),
        _Pick(id=10, score=0.40, price_uzs=2_500_000, area="A", is_furnished=False),
    ]


def test_stratified_pick_returns_k_or_pool_size():
    user = _User(areas=["A", "B", "C", "D"])
    picks = stratified_pick(_pool(), user, k=8)
    assert len(picks) == 8


def test_stratified_pick_small_pool_no_pad():
    user = _User(areas=["A", "B"])
    pool = _pool()[:3]
    picks = stratified_pick(pool, user, k=8)
    assert len(picks) == 3


def test_stratified_pick_covers_at_least_three_areas_when_possible():
    user = _User(areas=["A", "B", "C", "D"])
    picks = stratified_pick(_pool(), user, k=8)
    distinct_areas = {p.area for p in picks}
    assert len(distinct_areas) >= 3


def test_stratified_pick_mixes_furnishing_when_possible():
    user = _User(areas=["A", "B", "C", "D"])
    picks = stratified_pick(_pool(), user, k=8)
    furn = {p.is_furnished for p in picks}
    assert furn == {True, False}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_coldstart.py -v`
Expected: ImportError (module not found).

- [ ] **Step 3: Create the coldstart module**

Create `apps/shared/matching/coldstart.py`:

```python
"""Cold-start detection and stratified digest picker.

A user is in cold-start while they have fewer than COLD_START_REACTIONS
matches in {liked, disliked, contacted}. Plan 3 never writes those
states; Plan 4 will. In the meantime, all users stay in cold-start.
"""

from collections import defaultdict
from statistics import median
from typing import Iterable, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.shared.enums import MatchState
from apps.shared.matching.config import COLD_START_REACTIONS
from apps.shared.models import Match


_REACTION_STATES = (MatchState.LIKED, MatchState.DISLIKED, MatchState.CONTACTED)


def is_cold_start(session: Session, user) -> bool:
    count = session.execute(
        select(func.count())
        .select_from(Match)
        .where(Match.user_id == user.id, Match.state.in_(_REACTION_STATES))
    ).scalar_one()
    return count < COLD_START_REACTIONS


def _quartile_buckets(items: Sequence) -> list[list]:
    """Split items into 4 buckets by price_uzs quartile (inclusive lower).

    Returns four lists; some may be empty for small pools.
    """
    if not items:
        return [[], [], [], []]
    sorted_items = sorted(items, key=lambda x: x.price_uzs)
    n = len(sorted_items)
    # cut points by index for evenly-sized buckets
    q1 = n // 4
    q2 = n // 2
    q3 = (3 * n) // 4
    return [
        sorted_items[:q1],
        sorted_items[q1:q2],
        sorted_items[q2:q3],
        sorted_items[q3:],
    ]


def stratified_pick(matches: Sequence, user, k: int = 8) -> list:
    """Pick up to k matches with quartile / area / furnishing diversity.

    Inputs:
      matches: iterable of objects exposing .score, .price_uzs, .area,
               .is_furnished, .id (or a Match row joined to its listing
               fields — the caller is responsible for providing those
               attributes).
      user:    must expose .areas (list of strings the user selected)
      k:       max picks (default 8)

    Returns: a list of length min(k, len(matches)).
    """
    if not matches:
        return []
    if len(matches) <= k:
        return sorted(matches, key=lambda m: -m.score)

    buckets = _quartile_buckets(matches)
    per_bucket = max(1, k // 4)

    picks: list = []
    seen_ids: set = set()
    for b in buckets:
        chosen = sorted(b, key=lambda m: -m.score)[:per_bucket]
        for c in chosen:
            if c.id not in seen_ids:
                picks.append(c)
                seen_ids.add(c.id)

    # Top up with overall highest-scored remaining if we're below k.
    remaining = sorted(
        (m for m in matches if m.id not in seen_ids), key=lambda m: -m.score
    )
    while len(picks) < k and remaining:
        c = remaining.pop(0)
        picks.append(c)
        seen_ids.add(c.id)

    picks = picks[:k]

    # Area constraint: ensure ≥3 distinct areas if the user has ≥3 areas.
    user_areas = getattr(user, "areas", []) or []
    if len(user_areas) >= 3:
        picks = _ensure_areas(picks, matches, min_distinct=3, k=k)

    # Furnishing mix: if all picks share furnishing AND alternate exists in pool.
    picks = _ensure_furnishing_mix(picks, matches, k=k)

    return picks


def _ensure_areas(picks: list, pool: Sequence, min_distinct: int, k: int) -> list:
    distinct = {p.area for p in picks}
    if len(distinct) >= min_distinct:
        return picks
    # Count picks per area; find the over-represented area.
    counts: dict[str, int] = defaultdict(int)
    for p in picks:
        counts[p.area] += 1
    in_pool_areas = {m.area for m in pool}
    missing_areas = list(in_pool_areas - distinct)
    if not missing_areas:
        return picks

    pick_ids = {p.id for p in picks}
    for missing in missing_areas:
        if len({p.area for p in picks}) >= min_distinct:
            break
        replacement = max(
            (m for m in pool if m.area == missing and m.id not in pick_ids),
            key=lambda m: m.score,
            default=None,
        )
        if replacement is None:
            continue
        # drop lowest-scored pick from the most over-represented area
        over_area = max(counts, key=lambda a: counts[a])
        victim = min((p for p in picks if p.area == over_area), key=lambda p: p.score)
        picks.remove(victim)
        pick_ids.remove(victim.id)
        counts[over_area] -= 1
        picks.append(replacement)
        pick_ids.add(replacement.id)
        counts[replacement.area] += 1

    return picks[:k]


def _ensure_furnishing_mix(picks: list, pool: Sequence, k: int) -> list:
    furn_values = {p.is_furnished for p in picks if p.is_furnished is not None}
    if len(furn_values) > 1 or not furn_values:
        return picks  # already mixed, or unknown — leave alone
    current = next(iter(furn_values))
    alternate_pool = [
        m for m in pool if m.is_furnished is not None and m.is_furnished != current
    ]
    if not alternate_pool:
        return picks  # no alternate available
    replacement = max(alternate_pool, key=lambda m: m.score)
    if replacement in picks:
        return picks
    victim = min(picks, key=lambda p: p.score)
    picks.remove(victim)
    picks.append(replacement)
    return picks[:k]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_coldstart.py -v`
Expected: 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/shared/matching/coldstart.py tests/unit/test_coldstart.py
git commit -m "feat(matching): cold-start gate + stratified digest picker"
```

---

## Task 5: Hard filters

**Files:**
- Create: `apps/shared/matching/filters.py`
- Create: `tests/unit/test_filters.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_filters.py`:

```python
from dataclasses import dataclass, field

import pytest

from apps.shared.enums import (
    GenderConstraint,
    ListingState,
    MatchState,
    PosterRole,
    SearchType,
    UserState,
)
from apps.shared.matching.filters import (
    SEARCH_TYPE_COMPAT,
    python_filter_pass,
    sql_filter_candidates,
)
from apps.shared.models import Base, Listing, User


@dataclass
class _Listing:
    rooms: int | None = 2
    area: str | None = "Yunusabad"
    location_text: str | None = "Юнусабад, ул. Лабзак"
    is_first_floor: bool | None = False
    bathroom_type: str | None = "private"
    has_parking: bool | None = True
    description_ru: str | None = "Хорошая квартира"
    gender_constraint_listing: str | None = GenderConstraint.ANY


def _user(**kw):
    @dataclass
    class U:
        id: int = 1
        rooms: int | None = None
        areas: list = field(default_factory=lambda: ["Yunusabad"])
        commute_max_minutes: int | None = None
        commute_origin: str | None = None
        commute_mode: str | None = None
        commute_origin_lat: float | None = None
        commute_origin_lng: float | None = None
        dealbreakers: list = field(default_factory=list)
        dealbreaker_keywords: list = field(default_factory=list)
        negative_area_mask: list = field(default_factory=list)
        gender_pref: str | None = None
        axis_priority: dict = field(default_factory=lambda: {})
    return U(**kw)


def test_search_type_compat_solo_accepts_whole_apt():
    assert "whole_apt_solo" in SEARCH_TYPE_COMPAT[SearchType.WHOLE_APT_SOLO]
    assert "whole_apt_family" in SEARCH_TYPE_COMPAT[SearchType.WHOLE_APT_SOLO]


def test_search_type_compat_shared_room_only_shared():
    compat = SEARCH_TYPE_COMPAT[SearchType.SHARED_ROOM]
    assert "shared_room" in compat
    assert "whole_apt_family" not in compat


def test_python_filter_rooms_mismatch_drops():
    user = _user(rooms=3, axis_priority={"rooms": "MUST"})
    listing = _Listing(rooms=2)
    assert python_filter_pass(user, listing) is False


def test_python_filter_rooms_any_passes():
    user = _user(rooms=None, axis_priority={"rooms": "MUST"})
    listing = _Listing(rooms=2)
    assert python_filter_pass(user, listing) is True


def test_python_filter_area_must_passes_on_tuman():
    user = _user(areas=["Yunusabad"], axis_priority={"area": "MUST"})
    listing = _Listing(area="Yunusabad", location_text="X")
    assert python_filter_pass(user, listing) is True


def test_python_filter_area_must_drops_when_tuman_mismatch_and_no_substring():
    user = _user(areas=["Chilanzar"], axis_priority={"area": "MUST"})
    listing = _Listing(area="Yunusabad", location_text="Yunusabad street")
    assert python_filter_pass(user, listing) is False


def test_python_filter_area_must_passes_via_substring():
    user = _user(areas=["Лабзак"], axis_priority={"area": "MUST"})
    listing = _Listing(area="Yunusabad", location_text="ул. Лабзак 10")
    assert python_filter_pass(user, listing) is True


def test_python_filter_dealbreaker_first_floor_drops():
    user = _user(dealbreakers=["no_first_floor"])
    listing = _Listing(is_first_floor=True)
    assert python_filter_pass(user, listing) is False


def test_python_filter_dealbreaker_shared_bathroom_drops():
    user = _user(dealbreakers=["no_shared_bathroom"])
    listing = _Listing(bathroom_type="shared")
    assert python_filter_pass(user, listing) is False


def test_python_filter_dealbreaker_parking_required():
    user = _user(dealbreakers=["must_have_parking"])
    listing = _Listing(has_parking=False)
    assert python_filter_pass(user, listing) is False


def test_python_filter_keyword_drops():
    user = _user(dealbreaker_keywords=["евроремонт"])
    listing = _Listing(description_ru="свежий евроремонт")
    assert python_filter_pass(user, listing) is False


def test_python_filter_negative_area_mask_drops():
    user = _user(negative_area_mask=["Yunusabad"])
    listing = _Listing(area="Yunusabad")
    assert python_filter_pass(user, listing) is False


def test_python_filter_gender_mismatch_drops():
    user = _user(gender_pref="female")
    listing = _Listing(gender_constraint_listing="male")
    assert python_filter_pass(user, listing) is False


def test_python_filter_gender_any_passes():
    user = _user(gender_pref="female")
    listing = _Listing(gender_constraint_listing=GenderConstraint.ANY)
    assert python_filter_pass(user, listing) is True


# SQL filter (integration test against testcontainers Postgres)
def test_sql_filter_drops_paused_user(engine, db_session):
    Base.metadata.create_all(engine)
    db_session.add(User(
        tg_user_id=501, state=UserState.PAUSED,
        search_type=SearchType.WHOLE_APT_SOLO,
        budget_min=1_000_000, budget_max=2_000_000,
        axis_priority={"budget": "MUST"},
        agent_filter="agents_ok",
    ))
    db_session.add(User(
        tg_user_id=502, state=UserState.ACTIVE,
        search_type=SearchType.WHOLE_APT_SOLO,
        budget_min=1_000_000, budget_max=2_000_000,
        axis_priority={"budget": "MUST"},
        agent_filter="agents_ok",
    ))
    db_session.flush()

    listing = Listing(
        source_url="https://www.olx.uz/x1", source_listing_id="x1",
        source_category="long_term_apt",
        title="t", description_raw="", state=ListingState.ACTIVE,
        price_uzs=1_500_000, search_type_listing=SearchType.WHOLE_APT_SOLO,
        poster_role=PosterRole.OWNER, phone_hash="p1",
    )
    db_session.add(listing)
    db_session.flush()

    users = sql_filter_candidates(db_session, listing)
    assert len(users) == 1
    assert users[0].tg_user_id == 502


def test_sql_filter_budget_must_drops_out_of_range(engine, db_session):
    Base.metadata.create_all(engine)
    u_strict = User(
        tg_user_id=601, state=UserState.ACTIVE,
        search_type=SearchType.WHOLE_APT_SOLO,
        budget_min=1_000_000, budget_max=2_000_000,
        axis_priority={"budget": "MUST"},
        agent_filter="agents_ok",
    )
    u_nice = User(
        tg_user_id=602, state=UserState.ACTIVE,
        search_type=SearchType.WHOLE_APT_SOLO,
        budget_min=1_000_000, budget_max=2_000_000,
        axis_priority={"budget": "NICE"},
        agent_filter="agents_ok",
    )
    db_session.add_all([u_strict, u_nice])
    db_session.flush()

    listing = Listing(
        source_url="https://www.olx.uz/x2", source_listing_id="x2",
        source_category="long_term_apt",
        title="t", description_raw="", state=ListingState.ACTIVE,
        price_uzs=3_000_000, search_type_listing=SearchType.WHOLE_APT_SOLO,
        poster_role=PosterRole.OWNER, phone_hash="p2",
    )
    db_session.add(listing)
    db_session.flush()

    users = sql_filter_candidates(db_session, listing)
    tg_ids = {u.tg_user_id for u in users}
    assert 601 not in tg_ids
    assert 602 in tg_ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_filters.py -v`
Expected: ImportError.

- [ ] **Step 3: Create the filters module**

Create `apps/shared/matching/filters.py`:

```python
"""Hard filters: SQL-side cheap pruning + Python-side per-listing checks."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.shared.enums import GenderConstraint, PosterRole, SearchType, UserState
from apps.shared.models import User


SEARCH_TYPE_COMPAT: dict[str, set[str]] = {
    SearchType.WHOLE_APT_FAMILY: {
        SearchType.WHOLE_APT_FAMILY,
        SearchType.WHOLE_APT_SOLO,
    },
    SearchType.WHOLE_APT_SOLO: {
        SearchType.WHOLE_APT_SOLO,
        SearchType.WHOLE_APT_FAMILY,
    },
    SearchType.SHARED_ROOM: {
        SearchType.SHARED_ROOM,
    },
    SearchType.LOOKING_FOR_ROOMMATE: {
        SearchType.LOOKING_FOR_ROOMMATE,
        SearchType.SHARED_ROOM,
    },
}


DEALBREAKER_MAP: dict[str, callable] = {
    "no_first_floor": lambda l: l.is_first_floor is False,
    "no_shared_bathroom": lambda l: l.bathroom_type != "shared",
    "must_have_parking": lambda l: l.has_parking is True,
}


def sql_filter_candidates(session: Session, listing) -> list[User]:
    """SQL-level cheap filters. Returns active User rows that could
    plausibly match this listing — caller must still apply Python-side
    filters (commute routing, dealbreakers, keywords, etc.)."""

    compat_types = list(SEARCH_TYPE_COMPAT.keys())  # build per-user
    # We pivot: for each user.search_type, listing.search_type_listing
    # must be in SEARCH_TYPE_COMPAT[user.search_type]. Expressed as:
    #   user.search_type IN keys WHERE listing.search_type_listing IN compat[key]
    listing_st = listing.search_type_listing
    matching_user_types = [
        ust for ust, listing_set in SEARCH_TYPE_COMPAT.items()
        if listing_st in listing_set
    ]
    if not matching_user_types:
        return []

    stmt = (
        select(User)
        .where(User.state == UserState.ACTIVE)
        .where(User.search_type.in_(matching_user_types))
    )

    # Budget MUST gate
    if listing.price_uzs is not None:
        stmt = stmt.where(
            (User.axis_priority["budget"].astext == "NICE")
            | (
                (User.budget_min.is_(None) | (User.budget_min <= listing.price_uzs))
                & (User.budget_max.is_(None) | (User.budget_max >= listing.price_uzs))
            )
        )

    # Agent filter
    if listing.poster_role == PosterRole.AGENT:
        stmt = stmt.where(User.agent_filter == "agents_ok")

    # Seen set
    stmt = stmt.where(~User.seen_set.any(listing.id))

    # Distrust set on phone_hash
    if listing.phone_hash:
        stmt = stmt.where(~User.distrust_set.any(listing.phone_hash))

    return list(session.execute(stmt).scalars().all())


def python_filter_pass(user, listing) -> bool:
    """Per-listing Python filters that SQL can't cheaply do.

    Returns True if the (user, listing) pair survives ALL filters.
    """
    # Rooms MUST
    if (user.axis_priority or {}).get("rooms") == "MUST" and user.rooms is not None:
        if listing.rooms != user.rooms:
            return False

    # Area MUST
    if (user.axis_priority or {}).get("area") == "MUST":
        if not _area_match(user.areas or [], listing):
            return False

    # Negative area mask (always applied)
    if user.negative_area_mask and listing.area in user.negative_area_mask:
        return False

    # Structured dealbreakers
    for db_key in (user.dealbreakers or []):
        check = DEALBREAKER_MAP.get(db_key)
        if check is None:
            continue
        if not check(listing):
            return False

    # Dealbreaker keywords
    desc = (listing.description_ru or "").lower()
    for kw in (user.dealbreaker_keywords or []):
        if kw.lower() in desc:
            return False

    # Gender compatibility (only meaningful for shared room / roommate)
    if user.gender_pref and user.gender_pref != GenderConstraint.ANY:
        lc = listing.gender_constraint_listing
        if lc and lc != GenderConstraint.ANY and lc != user.gender_pref:
            return False

    return True


def _area_match(user_areas: list[str], listing) -> bool:
    if not user_areas:
        return True
    listing_area = listing.area
    loc = (listing.location_text or "").lower()
    for a in user_areas:
        if a == listing_area:
            return True
        if a.lower() in loc:
            return True
    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_filters.py -v`
Expected: 15 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/shared/matching/filters.py tests/unit/test_filters.py
git commit -m "feat(matching): SQL + Python hard filters"
```

---

## Task 6: Scoring formula

**Files:**
- Create: `apps/shared/matching/score.py`
- Create: `tests/unit/test_scoring.py`

**Note:** This task computes the score given (user, listing). Commute routing is invoked here when MUST/NICE; the existing `apps/shared/geo/yandex.py` exposes `geocode()` but not routing. We add a small `route_minutes()` helper as part of this task and stub it for unit tests.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_scoring.py`:

```python
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from apps.shared.enums import PosterRole
from apps.shared.matching import config as cfg
from apps.shared.matching.score import (
    budget_score,
    commute_score,
    cosine_normalized,
    freshness_score,
    score_listing_for_user,
)


def test_budget_score_in_range():
    assert budget_score(1_500_000, 1_000_000, 2_000_000) == 1.0


def test_budget_score_over_max_decays():
    assert 0 < budget_score(2_500_000, 1_000_000, 2_000_000) < 1.0


def test_budget_score_at_1_5x_max_zero():
    assert budget_score(3_000_000, 1_000_000, 2_000_000) == 0.0


def test_commute_score_in_range():
    assert commute_score(15, 30) == 1.0


def test_commute_score_over_decays():
    assert 0 < commute_score(35, 30) < 1.0


def test_commute_score_at_1_5x_zero():
    assert commute_score(45, 30) == 0.0


def test_freshness_decay_half_at_14_days():
    now = datetime.now(timezone.utc)
    fourteen = now - timedelta(days=14)
    assert abs(freshness_score(fourteen) - 0.5) < 1e-6


def test_freshness_fresh_close_to_one():
    now = datetime.now(timezone.utc) - timedelta(minutes=5)
    assert freshness_score(now) > 0.99


def test_cosine_normalized_bounds():
    assert cosine_normalized(1.0) == 1.0
    assert cosine_normalized(-1.0) == 0.0
    assert cosine_normalized(0.0) == 0.5


@dataclass
class _Listing:
    id: int = 1
    embedding: list = field(default_factory=lambda: [1.0, 0.0, 0.0])
    price_uzs: int = 1_500_000
    posted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc) - timedelta(hours=2))
    area: str = "Yunusabad"
    lat: float | None = 41.3
    lng: float | None = 69.2
    poster_role: str = PosterRole.OWNER
    risk_score: int = 0
    is_furnished: bool | None = True
    has_parking: bool | None = True
    rooms: int | None = 2
    is_first_floor: bool | None = False
    bathroom_type: str | None = "private"
    summary_one_line: str | None = None
    agent_fee_text: str | None = None
    risk_flags: dict | None = None
    description_ru: str | None = ""
    gender_constraint_listing: str | None = "any"
    location_text: str | None = "Yunusabad, ulitsa"


@dataclass
class _User:
    id: int = 1
    preference_embedding: list = field(default_factory=lambda: [1.0, 0.0, 0.0])
    budget_min: int = 1_000_000
    budget_max: int = 2_000_000
    commute_max_minutes: int | None = None
    commute_origin: str | None = None
    commute_origin_lat: float | None = None
    commute_origin_lng: float | None = None
    commute_mode: str | None = None
    axis_priority: dict = field(default_factory=lambda: {
        "budget": "MUST", "area": "NICE", "rooms": "NICE", "commute": "NICE", "furnishing": "NICE",
    })
    rooms: int | None = None
    areas: list = field(default_factory=lambda: ["Yunusabad"])
    is_furnished_pref: bool | None = None


def test_score_returns_in_unit_range_for_basic_match():
    user = _User()
    listing = _Listing()
    score, reasons, components = score_listing_for_user(user, listing)
    assert -0.1 <= score <= 1.0
    assert isinstance(reasons, list)
    assert len(reasons) > 0


def test_score_drops_with_high_risk():
    user = _User()
    fresh = _Listing(risk_score=0)
    risky = _Listing(risk_score=3)
    s_fresh, _, _ = score_listing_for_user(user, fresh)
    s_risky, _, _ = score_listing_for_user(user, risky)
    assert s_fresh > s_risky


def test_score_drops_with_age():
    user = _User()
    fresh = _Listing(posted_at=datetime.now(timezone.utc) - timedelta(minutes=10))
    old = _Listing(posted_at=datetime.now(timezone.utc) - timedelta(days=30))
    s_fresh, _, _ = score_listing_for_user(user, fresh)
    s_old, _, _ = score_listing_for_user(user, old)
    assert s_fresh > s_old


def test_score_commute_used_when_must(monkeypatch):
    user = _User(
        commute_max_minutes=30, commute_mode="car",
        commute_origin="X", commute_origin_lat=41.0, commute_origin_lng=69.0,
        axis_priority={"budget": "MUST", "commute": "MUST"},
    )
    listing = _Listing()
    with patch(
        "apps.shared.matching.score.route_minutes",
        return_value=20,
    ):
        score, reasons, components = score_listing_for_user(user, listing)
    assert components.commute_minutes == 20
    assert any("🚇 20 мин до работы" in r for r in reasons)


def test_score_no_commute_when_origin_missing():
    user = _User(commute_origin=None, commute_origin_lat=None)
    listing = _Listing()
    score, reasons, components = score_listing_for_user(user, listing)
    assert components.commute_minutes is None
    assert not any("🚇" in r for r in reasons)


def test_score_owner_higher_than_agent():
    user = _User()
    owner = _Listing(poster_role=PosterRole.OWNER)
    agent = _Listing(poster_role=PosterRole.AGENT)
    s_owner, _, _ = score_listing_for_user(user, owner)
    s_agent, _, _ = score_listing_for_user(user, agent)
    assert s_owner > s_agent
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_scoring.py -v`
Expected: ImportError.

- [ ] **Step 3: Add `route_minutes` to `apps/shared/geo/yandex.py`**

Read the existing file first to keep the same style. Then append:

```python
def route_minutes(
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
    mode: str = "car",
) -> int | None:
    """Return travel time in minutes from origin → dest, or None on failure.

    `mode` is one of {'walk', 'car', 'public'}. Plan 3 includes a thin
    implementation; Plan 1 only used geocoding.
    """
    # Minimal implementation: call Yandex Routing API if configured;
    # otherwise return a crude great-circle estimate at 30 km/h.
    import math

    R = 6371.0  # km
    phi1 = math.radians(origin_lat)
    phi2 = math.radians(dest_lat)
    dphi = math.radians(dest_lat - origin_lat)
    dlam = math.radians(dest_lng - origin_lng)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    km = 2 * R * math.asin(math.sqrt(a))
    avg_speed = {"walk": 5.0, "car": 30.0, "public": 18.0}.get(mode, 20.0)
    minutes = int((km / avg_speed) * 60)
    return max(1, minutes)
```

(A real Yandex Routing API integration belongs in a later iteration; for Plan 3 verification, the great-circle fallback is sufficient and deterministic for tests.)

- [ ] **Step 4: Create the scoring module**

Create `apps/shared/matching/score.py`:

```python
"""Scoring formula: hard filters already passed, now compute a score
and a frozen reasons[] array."""

from datetime import datetime, timezone

from apps.shared.enums import PosterRole
from apps.shared.geo.yandex import route_minutes
from apps.shared.matching import config as cfg
from apps.shared.matching.reasons import ScoreComponents, build_reasons


def cosine_normalized(raw: float) -> float:
    """Map raw cosine [-1, 1] to [0, 1]."""
    return max(0.0, min(1.0, (1.0 + raw) / 2.0))


def _cosine_raw(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def budget_score(price: int | None, lo: int | None, hi: int | None) -> float:
    if price is None or hi is None or hi == 0:
        return 0.5
    if price <= hi:
        return 1.0
    if price >= hi * 1.5:
        return 0.0
    return 1.0 - (price - hi) / (hi * 0.5)


def commute_score(minutes: int | None, max_minutes: int | None) -> float:
    if minutes is None or max_minutes is None or max_minutes == 0:
        return 0.5
    if minutes <= max_minutes:
        return 1.0
    if minutes >= max_minutes * 1.5:
        return 0.0
    return 1.0 - (minutes - max_minutes) / (max_minutes * 0.5)


def freshness_score(posted_at: datetime | None) -> float:
    if posted_at is None:
        return 0.5
    now = datetime.now(timezone.utc)
    age_days = max(0.0, (now - posted_at).total_seconds() / 86400.0)
    return 0.5 ** (age_days / 14.0)


def source_rep(listing) -> float:
    if listing.poster_role == PosterRole.OWNER:
        return 1.0
    if listing.poster_role == PosterRole.AGENT:
        return 0.7
    return 0.5


def axis_bonus(user, listing) -> float:
    """Fraction of NICE axes satisfied. Skipped axes don't count."""
    prio = user.axis_priority or {}
    nice_axes = [k for k, v in prio.items() if v == "NICE"]
    if not nice_axes:
        return 0.5

    satisfied = 0
    counted = 0
    for axis in nice_axes:
        if axis == "budget":
            if user.budget_max and listing.price_uzs and listing.price_uzs <= user.budget_max:
                satisfied += 1
            counted += 1
        elif axis == "area":
            if user.areas and listing.area in (user.areas or []):
                satisfied += 1
            counted += 1
        elif axis == "rooms":
            if user.rooms is not None and listing.rooms == user.rooms:
                satisfied += 1
            counted += 1
        elif axis == "commute":
            # measured separately; if commute is NICE, we may not have a
            # measurement — treat unmeasured as neutral by skipping.
            continue
        elif axis == "furnishing":
            # Plan 3: user-side furnishing pref isn't a column; skip.
            continue
        else:
            continue
    if counted == 0:
        return 0.5
    return satisfied / counted


def score_listing_for_user(user, listing) -> tuple[float, list[str], ScoreComponents]:
    """Compute (score, reasons, components) for a (user, listing) pair.

    Assumes hard filters have already passed.
    """
    components = ScoreComponents()
    components.cosine = cosine_normalized(
        _cosine_raw(user.preference_embedding or [], listing.embedding or [])
    )
    components.budget_score = budget_score(listing.price_uzs, user.budget_min, user.budget_max)
    components.freshness = freshness_score(listing.posted_at)
    components.source_rep = source_rep(listing)
    components.axis_bonus = axis_bonus(user, listing)
    components.risk_penalty = min(3, getattr(listing, "risk_score", 0) or 0)

    commute_used = False
    if (
        user.commute_origin_lat is not None
        and user.commute_origin_lng is not None
        and listing.lat is not None
        and listing.lng is not None
    ):
        mins = route_minutes(
            user.commute_origin_lat, user.commute_origin_lng,
            listing.lat, listing.lng,
            mode=user.commute_mode or "car",
        )
        components.commute_minutes = mins
        components.commute = commute_score(mins, user.commute_max_minutes)
        commute_used = True

    # Final weighted sum
    score = (
        cfg.W_COSINE * components.cosine
        + cfg.W_FRESHNESS * components.freshness
        + cfg.W_SOURCE_REP * components.source_rep
        + cfg.W_AXIS_BONUS * components.axis_bonus
        - cfg.W_RISK * (components.risk_penalty / 3.0)
    )

    prio = user.axis_priority or {}
    if prio.get("budget") == "NICE":
        score += cfg.W_BUDGET * components.budget_score
    if commute_used and prio.get("commute") in (None, "NICE", "MUST"):
        # commute included; MUST already gated by filter
        score += cfg.W_COMMUTE * getattr(components, "commute", 0.5)

    reasons = build_reasons(user, listing, components)
    return score, reasons, components
```

**Note:** `ScoreComponents.commute` is set ad-hoc above; extend the dataclass in `reasons.py` if your linter complains:

Modify `apps/shared/matching/reasons.py` `ScoreComponents` to add the field:

```python
@dataclass
class ScoreComponents:
    cosine: float | None = None
    budget_score: float | None = None
    commute_minutes: int | None = None
    commute: float | None = None          # ← new
    freshness: float | None = None
    source_rep: float | None = None
    axis_bonus: float | None = None
    risk_penalty: int = 0
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_scoring.py tests/unit/test_reasons.py -v`
Expected: all tests PASS (15 + 11 = 26).

- [ ] **Step 6: Commit**

```bash
git add apps/shared/matching/score.py apps/shared/matching/reasons.py apps/shared/geo/yandex.py tests/unit/test_scoring.py
git commit -m "feat(matching): scoring formula + commute routing helper"
```

---

## Task 7: Telegram send wrapper

**Files:**
- Create: `apps/shared/telegram_send.py`
- Create: `tests/unit/test_telegram_send.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_telegram_send.py`:

```python
from dataclasses import dataclass, field

from apps.shared.telegram_send import format_match_text


@dataclass
class _Listing:
    rooms: int | None = 2
    area: str | None = "Yunusabad"
    source_url: str = "https://www.olx.uz/x"
    summary_one_line: str | None = "балкон, рядом метро"


def test_format_match_text_basic():
    listing = _Listing()
    reasons = ["💰 1 400 000 UZS · в твоём бюджете", "🆕 12 мин назад", "📍 Юнусабад"]
    text = format_match_text(listing, reasons)
    assert "🏠 2-комн., Юнусабад" in text
    assert "💰 1 400 000 UZS" in text
    assert "балкон, рядом метро" in text
    assert "🔗 https://www.olx.uz/x" in text


def test_format_match_text_with_prefix():
    listing = _Listing()
    text = format_match_text(listing, reasons=["🆕 5 мин назад"], prefix="🔥 Свежий топ-вариант")
    assert text.splitlines()[0] == "🔥 Свежий топ-вариант"


def test_format_match_text_no_summary():
    listing = _Listing(summary_one_line=None)
    text = format_match_text(listing, reasons=["📍 Юнусабад"])
    assert "🏠" in text
    assert "🔗" in text
    # no blank summary block leaking
    assert "\n\n\n" not in text


def test_format_match_text_no_rooms():
    listing = _Listing(rooms=None)
    text = format_match_text(listing, reasons=[])
    assert "🏠 квартира, Юнусабад" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_telegram_send.py -v`
Expected: ImportError.

- [ ] **Step 3: Create the telegram_send module**

Create `apps/shared/telegram_send.py`:

```python
"""Sync wrapper around aiogram Bot for use from Celery workers.

Each call creates and closes its own Bot session — overhead is irrelevant
at MVP scale (5–10 users × ~8 messages/day). If we ever fan out to
thousands, replace with a pooled bot.
"""

import asyncio
import logging

from aiogram import Bot
from aiogram.types import InputMediaPhoto

from apps.shared.config import settings
from apps.shared.matching.reasons import rooms_str, tuman_ru

log = logging.getLogger(__name__)


def format_match_text(listing, reasons: list[str], prefix: str = "") -> str:
    lines: list[str] = []
    if prefix:
        lines.append(prefix)
    header = f"🏠 {rooms_str(listing.rooms)}, {tuman_ru(listing.area)}"
    lines.append(header)
    lines.extend(reasons)
    if listing.summary_one_line:
        lines.append("")
        lines.append(listing.summary_one_line)
    lines.append("")
    lines.append(f"🔗 {listing.source_url}")
    return "\n".join(lines)


def send_match_message(user, listing, match, prefix: str = "", reply_markup=None) -> None:
    asyncio.run(_async_send_match_message(user, listing, match, prefix, reply_markup))


def send_digest_header(user, count: int) -> None:
    asyncio.run(_async_send_digest_header(user, count))


async def _async_send_match_message(user, listing, match, prefix, reply_markup):
    bot = Bot(token=settings.telegram_bot_token)
    try:
        text = format_match_text(listing, match.reasons, prefix=prefix)
        if listing.image_urls:
            try:
                await bot.send_media_group(
                    chat_id=user.tg_user_id,
                    media=[InputMediaPhoto(media=u) for u in listing.image_urls[:4]],
                )
            except Exception as e:
                log.warning("media group send failed for tg=%s: %s", user.tg_user_id, e)
        await bot.send_message(
            chat_id=user.tg_user_id, text=text, reply_markup=reply_markup,
        )
    finally:
        await bot.session.close()


async def _async_send_digest_header(user, count: int):
    bot = Bot(token=settings.telegram_bot_token)
    try:
        text = f"Доброе утро ☀️ Подобрал {count} вариантов на сегодня"
        await bot.send_message(chat_id=user.tg_user_id, text=text)
    finally:
        await bot.session.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_telegram_send.py -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/shared/telegram_send.py tests/unit/test_telegram_send.py
git commit -m "feat(matching): sync aiogram wrapper for worker→Telegram sends"
```

---

## Task 8: Bot keyboards for match actions

**Files:**
- Modify: `apps/bot/keyboards.py`
- Create: `tests/unit/test_match_keyboards.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_match_keyboards.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_match_keyboards.py -v`
Expected: ImportError.

- [ ] **Step 3: Add keyboards to `apps/bot/keyboards.py`**

Append to `apps/bot/keyboards.py`:

```python
def match_actions_kb(match_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="👍", callback_data=f"like:{match_id}"),
        InlineKeyboardButton(text="👎", callback_data=f"dislike:{match_id}"),
        InlineKeyboardButton(text="📞 Контакт", callback_data=f"contact:{match_id}"),
    ]])


def dislike_reasons_kb(match_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💸 дорого",          callback_data=f"dislike_reason:expensive:{match_id}"),
            InlineKeyboardButton(text="📍 район",           callback_data=f"dislike_reason:area:{match_id}"),
        ],
        [
            InlineKeyboardButton(text="🐟 подозрительно",   callback_data=f"dislike_reason:fishy:{match_id}"),
            InlineKeyboardButton(text="👁 видел",           callback_data=f"dislike_reason:seen:{match_id}"),
        ],
    ])
```

If `InlineKeyboardButton` and `InlineKeyboardMarkup` are already imported at the top of the file, leave the imports alone. If not, add them.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_match_keyboards.py -v`
Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/bot/keyboards.py tests/unit/test_match_keyboards.py
git commit -m "feat(bot): match action keyboards"
```

---

## Task 9: Stub callback handlers

**Files:**
- Create: `apps/bot/handlers/match_callbacks.py`
- Modify: `apps/bot/handlers/__init__.py` (if needed)
- Modify: `apps/bot/main.py`
- Create: `tests/unit/test_match_callbacks.py`

- [ ] **Step 1: Inspect the existing handler-registration pattern**

Read `apps/bot/main.py` and `apps/bot/handlers/__init__.py`. Note the router name and how onboarding/settings/commands routers are registered. Mirror that pattern in the next steps.

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_match_callbacks.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from apps.bot.handlers.match_callbacks import (
    on_contact,
    on_dislike_open,
    on_dislike_reason,
    on_like,
)
from apps.shared.enums import ListingState, MatchState
from apps.shared.models import Base, Event, Listing, Match


def _make_cb(data: str, user_id: int = 123):
    cb = AsyncMock()
    cb.data = data
    cb.from_user = MagicMock(id=user_id, username="u")
    cb.message = AsyncMock()
    cb.message.text = "🏠 2-комн., Юнусабад\n💰 1 400 000 UZS"
    cb.answer = AsyncMock()
    return cb


@pytest.mark.asyncio
async def test_on_like_writes_event_and_edits_message(engine, db_session):
    Base.metadata.create_all(engine)
    cb = _make_cb("like:42")
    with patch("apps.bot.handlers.match_callbacks.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        await on_like(cb)
    db_session.flush()
    ev = db_session.execute(
        select(Event).where(Event.kind == "match_btn_like")
    ).scalar_one()
    assert ev.match_id == 42
    assert ev.user_id == 123
    cb.message.edit_reply_markup.assert_called_once()
    cb.message.edit_text.assert_called_once()
    cb.answer.assert_called_once()


@pytest.mark.asyncio
async def test_on_dislike_open_writes_event_and_swaps_kb(engine, db_session):
    Base.metadata.create_all(engine)
    cb = _make_cb("dislike:7")
    with patch("apps.bot.handlers.match_callbacks.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        await on_dislike_open(cb)
    db_session.flush()
    ev = db_session.execute(
        select(Event).where(Event.kind == "match_btn_dislike_open")
    ).scalar_one()
    assert ev.match_id == 7
    cb.message.edit_reply_markup.assert_called_once()
    cb.message.edit_text.assert_not_called()  # only kb swap


@pytest.mark.asyncio
async def test_on_dislike_reason_records_reason(engine, db_session):
    Base.metadata.create_all(engine)
    cb = _make_cb("dislike_reason:fishy:7")
    with patch("apps.bot.handlers.match_callbacks.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        await on_dislike_reason(cb)
    db_session.flush()
    ev = db_session.execute(
        select(Event).where(Event.kind == "match_btn_dislike_reason")
    ).scalar_one()
    assert ev.payload["reason"] == "fishy"
    assert ev.match_id == 7


@pytest.mark.asyncio
async def test_on_contact_reveals_phone(engine, db_session):
    Base.metadata.create_all(engine)
    listing = Listing(
        source_url="https://www.olx.uz/x", source_listing_id="x",
        source_category="long_term_apt",
        title="t", description_raw="", state=ListingState.ACTIVE,
        contact_phone_raw="+998901112233",
    )
    db_session.add(listing)
    db_session.flush()
    match = Match(user_id=123, listing_id=listing.id, score=0.5, reasons=[])
    db_session.add(match)
    db_session.flush()

    cb = _make_cb(f"contact:{match.id}")
    cb.message.answer = AsyncMock()
    with patch("apps.bot.handlers.match_callbacks.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        await on_contact(cb)

    cb.message.answer.assert_called_once()
    sent = cb.message.answer.call_args[0][0]
    assert "+998901112233" in sent
    assert listing.source_url in sent
    cb.message.edit_reply_markup.assert_called_once()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_match_callbacks.py -v`
Expected: ImportError.

- [ ] **Step 4: Create the handler module**

Create `apps/bot/handlers/match_callbacks.py`:

```python
"""Stub callback handlers for match action buttons.

Plan 3 does NOT transition matches.state — it only writes events. Plan 4
will own the ML feedback path. The one exception is the contact button:
it reveals the listing's phone number, which is the only way the digest
is useful for verification before Plan 4 ships.
"""

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select

from apps.bot.keyboards import dislike_reasons_kb
from apps.shared.db import session_scope
from apps.shared.models import Event, Listing, Match

log = logging.getLogger(__name__)

router = Router(name="match_callbacks")


@router.callback_query(F.data.startswith("like:"))
async def on_like(cb: CallbackQuery) -> None:
    match_id = int(cb.data.split(":", 1)[1])
    with session_scope() as s:
        s.add(Event(
            kind="match_btn_like",
            user_id=cb.from_user.id, match_id=match_id,
        ))
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.edit_text((cb.message.text or "") + "\n\n✅ Запомнил.")
    await cb.answer()


@router.callback_query(F.data.startswith("dislike:"))
async def on_dislike_open(cb: CallbackQuery) -> None:
    match_id = int(cb.data.split(":", 1)[1])
    with session_scope() as s:
        s.add(Event(
            kind="match_btn_dislike_open",
            user_id=cb.from_user.id, match_id=match_id,
        ))
    await cb.message.edit_reply_markup(reply_markup=dislike_reasons_kb(match_id))
    await cb.answer()


@router.callback_query(F.data.startswith("dislike_reason:"))
async def on_dislike_reason(cb: CallbackQuery) -> None:
    _, reason, mid = cb.data.split(":")
    with session_scope() as s:
        s.add(Event(
            kind="match_btn_dislike_reason",
            user_id=cb.from_user.id, match_id=int(mid),
            payload={"reason": reason},
        ))
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.edit_text((cb.message.text or "") + "\n\n👌")
    await cb.answer()


@router.callback_query(F.data.startswith("contact:"))
async def on_contact(cb: CallbackQuery) -> None:
    match_id = int(cb.data.split(":", 1)[1])
    with session_scope() as s:
        m = s.get(Match, match_id)
        listing = s.get(Listing, m.listing_id) if m else None
        phone = (listing.contact_phone_raw if listing else None) or "—"
        url = listing.source_url if listing else ""
        s.add(Event(
            kind="match_btn_contact",
            user_id=cb.from_user.id, match_id=match_id,
        ))
    await cb.message.answer(f"📞 {phone}\n\n🔗 {url}")
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.answer()
```

- [ ] **Step 5: Register the router in `apps/bot/main.py`**

Edit `apps/bot/main.py`. The current imports (lines 11–12) look like:

```python
from apps.bot.handlers import commands, onboarding
from apps.bot.handlers import settings as settings_handler
```

Replace with:

```python
from apps.bot.handlers import commands, match_callbacks, onboarding
from apps.bot.handlers import settings as settings_handler
```

The current router-registration block (lines 24–26) looks like:

```python
dp.include_router(onboarding.router)
dp.include_router(settings_handler.router)
dp.include_router(commands.router)
```

Replace with:

```python
dp.include_router(onboarding.router)
dp.include_router(settings_handler.router)
dp.include_router(commands.router)
dp.include_router(match_callbacks.router)
```

`apps/bot/handlers/__init__.py` does not need to change — handlers are imported as modules, not re-exported.

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_match_callbacks.py -v`
Expected: 4 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/bot/handlers/match_callbacks.py apps/bot/main.py tests/unit/test_match_callbacks.py
git commit -m "feat(bot): stub match action callbacks (event-log + edit only)"
```

---

## Task 10: Match fanout task + enrich hook

**Files:**
- Create: `apps/workers/tasks/match.py`
- Modify: `apps/workers/tasks/enrich.py` (one-line dispatch hook in `enrich_listing`)
- Modify: `apps/workers/celery_app.py` (include the new module)
- Create: `tests/unit/test_match_fanout.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_match_fanout.py`:

```python
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from apps.shared.enums import (
    GenderConstraint, ListingState, MatchState,
    PosterRole, SearchType, UserState,
)
from apps.shared.models import Base, Listing, Match, User


def _user(db_session, tg, **kw):
    defaults = dict(
        state=UserState.ACTIVE,
        search_type=SearchType.WHOLE_APT_SOLO,
        budget_min=1_000_000, budget_max=2_000_000,
        rooms=None,
        areas=["Yunusabad"],
        axis_priority={"budget": "MUST", "area": "NICE", "rooms": "NICE"},
        agent_filter="agents_ok",
        gender_pref=GenderConstraint.ANY,
        preference_embedding=[0.1] * 3072,
    )
    defaults.update(kw)
    u = User(tg_user_id=tg, **defaults)
    db_session.add(u)
    db_session.flush()
    return u


def _listing(db_session, **kw):
    defaults = dict(
        source="olx", source_listing_id=str(kw.get("id_suffix", "x")),
        source_category="long_term_apt",
        source_url=f"https://www.olx.uz/{kw.get('id_suffix', 'x')}",
        title="t", description_raw="", description_ru="чистая квартира",
        state=ListingState.ACTIVE,
        price_uzs=1_500_000, rooms=2, area="Yunusabad",
        search_type_listing=SearchType.WHOLE_APT_SOLO,
        gender_constraint_listing=GenderConstraint.ANY,
        poster_role=PosterRole.OWNER, phone_hash="ph",
        posted_at=datetime.now(UTC) - timedelta(minutes=15),
        embedding=[0.1] * 3072,
        risk_score=0, suppressed=False,
        is_furnished=True, has_parking=True, is_first_floor=False,
        bathroom_type="private",
        image_urls=[], image_phashes=[],
    )
    kw.pop("id_suffix", None)
    defaults.update(kw)
    l = Listing(**defaults)
    db_session.add(l)
    db_session.flush()
    return l


def test_fanout_inserts_matches_for_eligible_users(engine, db_session):
    from apps.workers.tasks.match import match_fanout_listing
    Base.metadata.create_all(engine)
    u1 = _user(db_session, tg=701)
    u2 = _user(db_session, tg=702, state=UserState.PAUSED)  # not active
    l = _listing(db_session, id_suffix="abc")
    db_session.commit()

    with patch("apps.workers.tasks.match.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        with patch("apps.workers.tasks.match.match_alert_instant"):
            match_fanout_listing.run(l.id)

    matches = db_session.query(Match).filter_by(listing_id=l.id).all()
    user_ids = {m.user_id for m in matches}
    assert u1.id in user_ids
    assert u2.id not in user_ids


def test_fanout_skips_suppressed_listing(engine, db_session):
    from apps.workers.tasks.match import match_fanout_listing
    Base.metadata.create_all(engine)
    _user(db_session, tg=801)
    l = _listing(db_session, id_suffix="sup", suppressed=True)
    db_session.commit()

    with patch("apps.workers.tasks.match.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        result = match_fanout_listing.run(l.id)
    assert result["ok"] is False
    assert db_session.query(Match).count() == 0


def test_fanout_skips_canonical_pointer(engine, db_session):
    from apps.workers.tasks.match import match_fanout_listing
    Base.metadata.create_all(engine)
    _user(db_session, tg=802)
    canonical = _listing(db_session, id_suffix="canon")
    db_session.flush()
    dup = _listing(db_session, id_suffix="dup", canonical_listing_id=canonical.id)
    db_session.commit()

    with patch("apps.workers.tasks.match.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        result = match_fanout_listing.run(dup.id)
    assert result["ok"] is False


def test_fanout_respects_insert_threshold(engine, db_session):
    """If score < INSERT_THRESHOLD, no match row is created."""
    from apps.workers.tasks.match import match_fanout_listing
    Base.metadata.create_all(engine)
    # Embedding orthogonal to listing → low cosine; bump risk to drag score down further.
    u = _user(db_session, tg=803, preference_embedding=[0.0] * 3071 + [1.0])
    l = _listing(
        db_session, id_suffix="lo",
        embedding=[1.0] + [0.0] * 3071,
        risk_score=3,
        posted_at=datetime.now(UTC) - timedelta(days=60),
    )
    db_session.commit()

    with patch("apps.workers.tasks.match.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        with patch("apps.workers.tasks.match.match_alert_instant"):
            match_fanout_listing.run(l.id)

    assert db_session.query(Match).filter_by(listing_id=l.id).count() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_match_fanout.py -v`
Expected: ImportError or attribute error.

- [ ] **Step 3: Create the match worker module**

Create `apps/workers/tasks/match.py`:

```python
"""Match fanout, instant alerts, threshold recompute, dead cleanup."""

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update

from apps.shared.db import session_scope
from apps.shared.enums import (
    DeliveredVia, ListingState, MatchState, UserState,
)
from apps.shared.matching import config as cfg
from apps.shared.matching.coldstart import is_cold_start
from apps.shared.matching.filters import python_filter_pass, sql_filter_candidates
from apps.shared.matching.score import score_listing_for_user
from apps.shared.models import Event, Listing, Match, User
from apps.workers.celery_app import app

log = logging.getLogger(__name__)


@app.task(name="match.fanout.listing", bind=True, max_retries=2, default_retry_delay=60)
def match_fanout_listing(self, listing_id: int) -> dict:
    with session_scope() as s:
        listing = s.get(Listing, listing_id)
        if listing is None or listing.state != ListingState.ACTIVE:
            return {"ok": False, "reason": "not eligible"}
        if listing.suppressed:
            return {"ok": False, "reason": "suppressed"}
        if listing.canonical_listing_id is not None:
            return {"ok": False, "reason": "canonical pointer"}

        candidates = sql_filter_candidates(s, listing)
        inserted = 0
        for user in candidates:
            if not python_filter_pass(user, listing):
                continue
            score, reasons, _ = score_listing_for_user(user, listing)
            if score < cfg.INSERT_THRESHOLD:
                continue
            m = Match(
                user_id=user.id, listing_id=listing.id,
                score=score, reasons=reasons,
                state=MatchState.PENDING,
            )
            s.add(m)
            s.flush()
            inserted += 1
            threshold = user.top_1pct_threshold or 999.0
            if score >= threshold and not is_cold_start(s, user):
                match_alert_instant.delay(m.id)
        return {"ok": True, "candidates": len(candidates), "inserted": inserted}


@app.task(name="match.alert.instant", bind=True, max_retries=2, default_retry_delay=60)
def match_alert_instant(self, match_id: int) -> dict:
    from apps.shared.telegram_send import send_match_message
    from apps.bot.keyboards import match_actions_kb

    with session_scope() as s:
        m = s.get(Match, match_id)
        if not m or m.state != MatchState.PENDING:
            return {"ok": False, "reason": "state changed"}
        user = s.get(User, m.user_id)
        if not user or user.state != UserState.ACTIVE:
            return {"ok": False, "reason": "user inactive"}

        now_tsk = datetime.now(ZoneInfo("Asia/Tashkent"))
        if now_tsk.hour >= cfg.QUIET_HOURS_START or now_tsk.hour < cfg.QUIET_HOURS_END:
            return {"ok": False, "reason": "quiet hours"}

        today_start = now_tsk.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
        delivered_today = s.execute(
            select(func.count()).select_from(Match)
            .where(Match.user_id == user.id,
                   Match.delivered_via == DeliveredVia.INSTANT,
                   Match.created_at >= today_start)
        ).scalar() or 0
        if delivered_today >= cfg.INSTANT_DAILY_CAP:
            return {"ok": False, "reason": "cap reached"}

        listing = s.get(Listing, m.listing_id)
        send_match_message(
            user, listing, m,
            prefix="🔥 Свежий топ-вариант",
            reply_markup=match_actions_kb(m.id),
        )
        m.state = MatchState.SENT
        m.delivered_via = DeliveredVia.INSTANT
        s.add(Event(
            kind="match_sent_instant",
            user_id=user.id, listing_id=listing.id, match_id=m.id,
        ))
        return {"ok": True}


@app.task(name="match.threshold.recompute")
def match_threshold_recompute() -> dict:
    """Daily 05:00 UTC: recompute per-user top_1pct_threshold."""
    with session_scope() as s:
        global_scores = [
            row[0] for row in s.execute(
                select(Match.score).where(
                    Match.created_at >= datetime.now(UTC) - timedelta(days=14)
                )
            )
        ]
        global_p99 = _percentile(global_scores, 99) if len(global_scores) >= cfg.THRESHOLD_MIN_GLOBAL else None

        user_ids = [r[0] for r in s.execute(
            select(User.id).where(User.state == UserState.ACTIVE)
        )]
        updated = 0
        for uid in user_ids:
            personal = [
                r[0] for r in s.execute(
                    select(Match.score).where(
                        Match.user_id == uid,
                        Match.created_at >= datetime.now(UTC) - timedelta(days=14),
                    )
                )
            ]
            if len(personal) >= cfg.THRESHOLD_MIN_PERSONAL:
                t = _percentile(personal, 99)
            elif global_p99 is not None:
                t = global_p99
            else:
                t = cfg.GLOBAL_TOP1PCT_BOOTSTRAP
            s.execute(
                update(User).where(User.id == uid).values(top_1pct_threshold=t)
            )
            updated += 1
        return {"updated": updated, "global_p99": global_p99}


@app.task(name="match.cleanup.dead")
def match_cleanup_dead() -> dict:
    """Mark matches whose listing is dead as dead too."""
    with session_scope() as s:
        result = s.execute(
            update(Match)
            .where(Match.state == MatchState.PENDING)
            .where(Match.listing_id.in_(
                select(Listing.id).where(Listing.state == ListingState.DEAD)
            ))
            .values(state=MatchState.DEAD)
        )
        return {"updated": result.rowcount or 0}


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sv = sorted(values)
    k = (len(sv) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sv) - 1)
    frac = k - lo
    return sv[lo] + (sv[hi] - sv[lo]) * frac
```

- [ ] **Step 4: Register the module in `apps/workers/celery_app.py`**

Edit `apps/workers/celery_app.py` `include=[...]` list — add `"apps.workers.tasks.match"`:

```python
include=[
    "apps.workers.tasks.scrape",
    "apps.workers.tasks.enrich",
    "apps.workers.tasks.recheck",
    "apps.workers.tasks.purge",
    "apps.workers.tasks.match",
],
```

- [ ] **Step 5: Hook fanout into the enrich wrapper**

Open `apps/workers/tasks/enrich.py`. Find the `enrich_listing` task body (the wrapper that calls `_enrich_one`). Replace its body with:

```python
@app.task(name="enrich.listing", bind=True, max_retries=3, default_retry_delay=120)
def enrich_listing(self, listing_id: int) -> dict:
    result = _enrich_one(listing_id)
    if result.get("ok"):
        from apps.workers.tasks.match import match_fanout_listing
        match_fanout_listing.delay(listing_id)
    return result
```

(Import is inside the function to avoid a circular import at module-load time.)

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_match_fanout.py -v`
Expected: 4 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/workers/tasks/match.py apps/workers/tasks/enrich.py apps/workers/celery_app.py tests/unit/test_match_fanout.py
git commit -m "feat(matching): match fanout + instant alert + threshold recompute + cleanup"
```

---

## Task 11: Daily digest task

**Files:**
- Create: `apps/workers/tasks/digest.py`
- Modify: `apps/workers/celery_app.py` (include + beat entry)
- Create: `tests/unit/test_digest_task.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_digest_task.py`:

```python
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from apps.shared.enums import DeliveredVia, ListingState, MatchState, UserState, SearchType
from apps.shared.models import Base, Event, Listing, Match, User


def _user(db_session, tg, **kw):
    defaults = dict(
        state=UserState.ACTIVE,
        search_type=SearchType.WHOLE_APT_SOLO,
        budget_min=1_000_000, budget_max=3_000_000,
        areas=["Yunusabad"],
        axis_priority={"budget": "NICE"},
        agent_filter="agents_ok",
        preference_embedding=[0.1] * 3072,
    )
    defaults.update(kw)
    u = User(tg_user_id=tg, **defaults)
    db_session.add(u)
    db_session.flush()
    return u


def _listing(db_session, **kw):
    defaults = dict(
        source="olx", source_listing_id=kw.get("source_listing_id", "d"),
        source_category="long_term_apt",
        source_url=f"https://www.olx.uz/{kw.get('source_listing_id', 'd')}",
        title="t", description_raw="",
        state=ListingState.ACTIVE,
        price_uzs=1_500_000, rooms=2, area="Yunusabad",
        is_furnished=True,
        posted_at=datetime.now(UTC) - timedelta(hours=2),
        image_urls=[], image_phashes=[],
    )
    defaults.update(kw)
    l = Listing(**defaults)
    db_session.add(l)
    db_session.flush()
    return l


def test_digest_skips_when_no_pending(engine, db_session):
    from apps.workers.tasks.digest import digest_send_for_user
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=701)
    db_session.commit()
    with patch("apps.workers.tasks.digest.session_scope") as ss, \
         patch("apps.workers.tasks.digest.send_digest_header") as h, \
         patch("apps.workers.tasks.digest.send_match_message") as m:
        ss.return_value.__enter__.return_value = db_session
        out = digest_send_for_user.run(u.id)
    assert out["matches"] == 0
    h.assert_not_called()
    m.assert_not_called()


def test_digest_sends_top_k_for_warm_user(engine, db_session):
    from apps.workers.tasks.digest import digest_send_for_user
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=702)
    # warm user: ≥10 reactions
    for i in range(11):
        l = _listing(db_session, source_listing_id=f"warm-{i}")
        db_session.add(Match(
            user_id=u.id, listing_id=l.id,
            score=0.4, reasons=[], state=MatchState.LIKED,
        ))
    # pending matches with varying scores
    for i in range(10):
        l = _listing(db_session, source_listing_id=f"p-{i}")
        db_session.add(Match(
            user_id=u.id, listing_id=l.id,
            score=0.5 + i * 0.01, reasons=["💰 test", "📍 Юнусабад"],
            state=MatchState.PENDING,
        ))
    db_session.commit()

    with patch("apps.workers.tasks.digest.session_scope") as ss, \
         patch("apps.workers.tasks.digest.send_digest_header") as h, \
         patch("apps.workers.tasks.digest.send_match_message") as m:
        ss.return_value.__enter__.return_value = db_session
        out = digest_send_for_user.run(u.id)

    assert out["matches"] == 8
    h.assert_called_once()
    assert m.call_count == 8


def test_digest_uses_stratifier_for_cold_user(engine, db_session):
    from apps.workers.tasks.digest import digest_send_for_user
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=703, areas=["Yunusabad", "Chilanzar", "Sergeli", "Almazar"])
    # Cold-start: no reactions
    # 12 pending matches across 4 areas, varied prices
    areas = ["Yunusabad", "Chilanzar", "Sergeli", "Almazar"]
    for i in range(12):
        l = _listing(
            db_session, source_listing_id=f"cs-{i}",
            area=areas[i % 4], price_uzs=1_000_000 + i * 100_000,
            is_furnished=bool(i % 2),
        )
        db_session.add(Match(
            user_id=u.id, listing_id=l.id,
            score=0.5 + i * 0.01, reasons=[], state=MatchState.PENDING,
        ))
    db_session.commit()

    with patch("apps.workers.tasks.digest.session_scope") as ss, \
         patch("apps.workers.tasks.digest.send_digest_header"), \
         patch("apps.workers.tasks.digest.send_match_message") as m:
        ss.return_value.__enter__.return_value = db_session
        out = digest_send_for_user.run(u.id)

    assert out["matches"] == 8
    assert m.call_count == 8


def test_digest_filters_dead_listings(engine, db_session):
    from apps.workers.tasks.digest import digest_send_for_user
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=704)
    l_alive = _listing(db_session, source_listing_id="alive")
    l_dead = _listing(db_session, source_listing_id="dead", state=ListingState.DEAD)
    db_session.add(Match(user_id=u.id, listing_id=l_alive.id, score=0.5, reasons=[], state=MatchState.PENDING))
    db_session.add(Match(user_id=u.id, listing_id=l_dead.id, score=0.9, reasons=[], state=MatchState.PENDING))
    db_session.commit()

    with patch("apps.workers.tasks.digest.session_scope") as ss, \
         patch("apps.workers.tasks.digest.send_digest_header"), \
         patch("apps.workers.tasks.digest.send_match_message") as m:
        ss.return_value.__enter__.return_value = db_session
        out = digest_send_for_user.run(u.id)

    assert out["matches"] == 1
    # The dead listing wasn't sent
    sent_listing = m.call_args[0][1]
    assert sent_listing.id == l_alive.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_digest_task.py -v`
Expected: ImportError.

- [ ] **Step 3: Create the digest worker module**

Create `apps/workers/tasks/digest.py`:

```python
"""Daily 09:00 Tashkent digest sender.

Beat fires `digest.send.daily` once at 04:00 UTC (= 09:00 Tashkent), which
fans out one `digest.send.user` task per active user.
"""

import logging
from collections import namedtuple

from sqlalchemy import select

from apps.bot.keyboards import match_actions_kb
from apps.shared.db import session_scope
from apps.shared.enums import DeliveredVia, ListingState, MatchState, UserState
from apps.shared.matching.coldstart import is_cold_start, stratified_pick
from apps.shared.models import Event, Listing, Match, User
from apps.shared.telegram_send import send_digest_header, send_match_message
from apps.workers.celery_app import app

log = logging.getLogger(__name__)


# stratifier expects objects exposing score, price_uzs, area, is_furnished, id
_Pick = namedtuple("_Pick", ["id", "score", "price_uzs", "area", "is_furnished", "listing_id"])


@app.task(name="digest.send.daily")
def digest_send_daily() -> dict:
    with session_scope() as s:
        ids = [r[0] for r in s.execute(
            select(User.id).where(User.state == UserState.ACTIVE)
        )]
    for uid in ids:
        digest_send_for_user.delay(uid)
    return {"users": len(ids)}


@app.task(name="digest.send.user", bind=True, max_retries=2, default_retry_delay=120)
def digest_send_for_user(self, user_id: int) -> dict:
    with session_scope() as s:
        user = s.get(User, user_id)
        if not user or user.state != UserState.ACTIVE:
            return {"ok": False, "matches": 0}

        rows = s.execute(
            select(Match, Listing)
            .join(Listing, Listing.id == Match.listing_id)
            .where(
                Match.user_id == user_id,
                Match.state == MatchState.PENDING,
                Listing.state == ListingState.ACTIVE,
            )
            .order_by(Match.score.desc())
            .limit(200)
        ).all()

        if not rows:
            return {"ok": True, "matches": 0}

        picks_carriers = [
            _Pick(
                id=m.id, score=m.score,
                price_uzs=l.price_uzs or 0, area=l.area or "",
                is_furnished=l.is_furnished, listing_id=l.id,
            )
            for m, l in rows
        ]
        listing_by_id = {l.id: l for _, l in rows}
        match_by_id = {m.id: m for m, _ in rows}

        if is_cold_start(s, user):
            picks = stratified_pick(picks_carriers, user, k=8)
        else:
            picks = picks_carriers[:8]

        send_digest_header(user, count=len(picks))
        for p in picks:
            match = match_by_id[p.id]
            listing = listing_by_id[p.listing_id]
            send_match_message(
                user, listing, match,
                reply_markup=match_actions_kb(match.id),
            )
            match.state = MatchState.SENT
            match.delivered_via = DeliveredVia.DIGEST
            s.add(Event(
                kind="match_sent_digest",
                user_id=user.id, listing_id=listing.id, match_id=match.id,
            ))
        return {"ok": True, "matches": len(picks)}
```

- [ ] **Step 4: Register the module in `apps/workers/celery_app.py`**

Add `"apps.workers.tasks.digest"` to the `include=[...]` list:

```python
include=[
    "apps.workers.tasks.scrape",
    "apps.workers.tasks.enrich",
    "apps.workers.tasks.recheck",
    "apps.workers.tasks.purge",
    "apps.workers.tasks.match",
    "apps.workers.tasks.digest",
],
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_digest_task.py -v`
Expected: 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/workers/tasks/digest.py apps/workers/celery_app.py tests/unit/test_digest_task.py
git commit -m "feat(matching): daily digest task"
```

---

## Task 12: Beat schedule additions

**Files:**
- Modify: `apps/workers/celery_app.py`
- Create: `tests/unit/test_beat_schedule_plan3.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_beat_schedule_plan3.py`:

```python
from apps.workers.celery_app import app


def test_digest_send_daily_scheduled():
    sched = app.conf.beat_schedule
    assert "digest-send-daily" in sched
    entry = sched["digest-send-daily"]
    assert entry["task"] == "digest.send.daily"
    # Should fire at 04:00 UTC (= 09:00 Tashkent)
    assert entry["schedule"].hour == {4}
    assert entry["schedule"].minute == {0}


def test_match_cleanup_dead_scheduled():
    sched = app.conf.beat_schedule
    assert "match-cleanup-dead" in sched
    assert sched["match-cleanup-dead"]["task"] == "match.cleanup.dead"
    entry = sched["match-cleanup-dead"]
    assert entry["schedule"].hour == {4}
    assert entry["schedule"].minute == {45}


def test_match_threshold_recompute_scheduled():
    sched = app.conf.beat_schedule
    assert "match-threshold-recompute" in sched
    assert sched["match-threshold-recompute"]["task"] == "match.threshold.recompute"
    entry = sched["match-threshold-recompute"]
    assert entry["schedule"].hour == {5}
    assert entry["schedule"].minute == {0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_beat_schedule_plan3.py -v`
Expected: KeyError — entries not present yet.

- [ ] **Step 3: Add beat entries**

Edit `apps/workers/celery_app.py`. After the existing `app.conf.beat_schedule.update({...})` block, append another update:

```python
app.conf.beat_schedule.update({
    "digest-send-daily": {
        "task": "digest.send.daily",
        "schedule": crontab(hour=4, minute=0),  # 04:00 UTC = 09:00 Tashkent
    },
    "match-cleanup-dead": {
        "task": "match.cleanup.dead",
        "schedule": crontab(hour=4, minute=45),
    },
    "match-threshold-recompute": {
        "task": "match.threshold.recompute",
        "schedule": crontab(hour=5, minute=0),
    },
})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_beat_schedule_plan3.py -v`
Expected: 3 tests PASS.

- [ ] **Step 5: Run the full unit test suite to catch regressions**

Run: `uv run pytest tests/unit/ -v`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/workers/celery_app.py tests/unit/test_beat_schedule_plan3.py
git commit -m "feat(matching): beat schedule entries for digest, cleanup, threshold"
```

---

## Task 13: Manual verification runbook

This task produces no code. It validates the full ingest → match → digest → button-tap loop end-to-end against the maintainer's Telegram account.

- [ ] **Step 1: Bring up the stack**

```bash
docker compose up -d --build
docker compose logs -f bot worker beat
```

Wait until logs show:
- `beat`: schedule loaded with `digest-send-daily`, `match-cleanup-dead`, `match-threshold-recompute`
- `worker`: tasks `match.fanout.listing`, `match.alert.instant`, `match.threshold.recompute`, `match.cleanup.dead`, `digest.send.daily`, `digest.send.user` registered
- `bot`: webhook set

- [ ] **Step 2: Confirm maintainer user is active**

Connect to Postgres:

```sql
SELECT id, tg_user_id, state, preference_embedding IS NOT NULL AS has_emb
FROM users
WHERE tg_user_id = <maintainer_tg_id>;
```

Expected: `state='active'`, `has_emb=true`. If state is not active, run `/start` in the bot and complete onboarding.

- [ ] **Step 3: Live fanout — enrich one listing**

Find a pending listing:

```sql
SELECT id, title FROM listings WHERE state='active' ORDER BY enriched_at DESC LIMIT 5;
```

Pick one ID. Trigger fanout from a worker shell:

```bash
docker compose exec worker python -c "
from apps.workers.tasks.match import match_fanout_listing
print(match_fanout_listing.apply(args=[<listing_id>]).result)
"
```

Expected output: `{"ok": True, "candidates": N, "inserted": M}` where N includes the maintainer, M ≥ 0.

Confirm a row exists:

```sql
SELECT id, score, reasons, state, delivered_via
FROM matches
WHERE user_id = <maintainer_user_id> AND listing_id = <listing_id>;
```

Expected: `state='pending'`, `reasons` is a non-empty array, `delivered_via IS NULL`.

- [ ] **Step 4: Live digest — trigger for maintainer**

```bash
docker compose exec worker python -c "
from apps.workers.tasks.digest import digest_send_for_user
print(digest_send_for_user.apply(args=[<maintainer_user_id>]).result)
"
```

Expected: a digest header arrives in Telegram, followed by 1–8 listing messages, each with a `[👍] [👎] [📞 Контакт]` row. Verify formatting:

- `🏠 N-комн., <area_ru>` on the first line
- price + budget marker, freshness, area, poster role on subsequent lines
- one-line summary (if present)
- `🔗 https://www.olx.uz/...` last

Confirm DB state:

```sql
SELECT state, delivered_via FROM matches
WHERE user_id = <maintainer_user_id> AND id = <one_of_the_sent_match_ids>;
```

Expected: `state='sent'`, `delivered_via='digest'`.

- [ ] **Step 5: Live button-tap verification**

Tap each button on one of the digest messages:

1. **`👍`** — message should edit to append "✅ Запомнил."; buttons disappear.
   ```sql
   SELECT * FROM events WHERE kind = 'match_btn_like'
     AND user_id = <maintainer_tg_id> ORDER BY ts DESC LIMIT 1;
   ```
   Expected: one row with the correct `match_id`.

2. **`👎`** on a different message — keyboard swaps to 4 reason buttons; tap `🐟 подозрительно`.
   ```sql
   SELECT kind, payload FROM events
   WHERE user_id = <maintainer_tg_id> AND kind LIKE 'match_btn_dislike%'
   ORDER BY ts DESC LIMIT 2;
   ```
   Expected: two rows — `match_btn_dislike_open` (no payload) and `match_btn_dislike_reason` with `payload->>'reason'='fishy'`.

3. **`📞 Контакт`** on a third message — a follow-up message appears with `📞 +998...` and the listing URL.
   ```sql
   SELECT kind FROM events WHERE kind = 'match_btn_contact' ORDER BY ts DESC LIMIT 1;
   ```
   Expected: one row.

- [ ] **Step 6: Live instant alert — bypass cold-start manually**

Insert 10 dummy reactions to exit cold-start:

```sql
INSERT INTO matches (user_id, listing_id, score, reasons, state)
SELECT <maintainer_user_id>, id, 0.5, ARRAY[]::text[], 'liked'
FROM listings ORDER BY id ASC LIMIT 10
ON CONFLICT DO NOTHING;

UPDATE users SET top_1pct_threshold = 0.0
WHERE id = <maintainer_user_id>;
```

Now enrich a fresh, high-quality listing (or re-run fanout on an existing one with a high cosine match). Expected: a `🔥 Свежий топ-вариант` message arrives within seconds, outside quiet hours.

```sql
SELECT delivered_via FROM matches WHERE id = <new_match_id>;
```

Expected: `delivered_via='instant'`.

Repeat 3× more to verify the cap — the **4th** alert is suppressed (check worker logs for `"reason": "cap reached"`).

- [ ] **Step 7: Live quiet-hours behaviour (optional, manual)**

Set system time to 23:00 Tashkent (or wait), trigger fanout on a high-scoring listing. Expected: no message arrives; match stays `state='pending'`.

- [ ] **Step 8: Cleanup test artifacts**

```sql
DELETE FROM matches WHERE user_id = <maintainer_user_id> AND state = 'liked' AND reasons = ARRAY[]::text[];
UPDATE users SET top_1pct_threshold = NULL WHERE id = <maintainer_user_id>;
```

- [ ] **Step 9: Final commit (runbook documentation)**

If you've kept a verification log, commit it now under `docs/runbooks/plan-3-verification-YYYY-MM-DD.md`. Otherwise this task ends without a commit.

---

## Plan complete

After all tasks pass, the system has:

- A `matches` table populated by push-from-enrich fanout
- Scoring with hard filters, 7 weighted components, frozen `reasons[]`
- Daily 04:00 UTC digest (Tashkent 09:00) with stratified picks for cold-start users
- Instant alerts with quiet-hour and daily-cap gating
- Working `👍 / 👎 / 📞` buttons that emit events and reveal phone numbers
- Daily threshold recompute and dead-match cleanup

Plan 4 builds on this: `matches.state` transitions, embedding updates, budget tightening, `distrust_set` writes, 48h/5d chase, Sunday check-in.
