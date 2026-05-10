# Scout — Plan 1: Foundation + Ingestion

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the Postgres + Celery + worker stack and a fully-working OLX ingest pipeline. By end of plan: cron-driven scrape of olx.uz fills the `listings` table with enriched, deduped, risk-scored, geocoded listings; dead listings get marked + purged on schedule. No bot, no users, no matching yet — those are Plans 2 & 3.

**Architecture:**
- One repo, one VPS, one docker-compose. Services: `api` (FastAPI for `/health` + admin), `worker` (Celery), `beat` (Celery scheduler), `postgres` (with pgvector), `redis`.
- Scraping is two-tier: `httpx` + `selectolax` for list/detail pages (cheap, fast); a small Playwright pool only for the OLX phone-reveal click. Auto-fallback to Playwright if `httpx` success rate drops.
- Enrichment is a pipeline of small composable functions, orchestrated by one Celery task per listing: language → translate → currency → LLM classify → image+pHash → geocode → risk → embed. Each step is independently testable.
- Dedup runs at the end of enrichment; tiered (phone/pHash → address+price → embedding cosine).
- Listing lifecycle: daily re-fetch flips dead listings, freshness decay applied at score time (Plan 3), 60d body-purge job.

**Tech stack (Plan 1 portion):**
- Python 3.12, `uv` for deps, `pyproject.toml`
- FastAPI, aiogram (bot is Plan 2; install dep but no usage yet)
- Celery + redis-py, celery-beat
- SQLAlchemy 2.x, Alembic, `psycopg[binary]`, `pgvector`
- `httpx`, `selectolax`, `playwright`, `imagehash`, `pillow`
- `pydantic-settings`, `tenacity`, `python-dotenv`
- `google-genai` (Gemini), Yandex Maps via `httpx`
- Tests: `pytest`, `pytest-asyncio`, `respx`, `testcontainers[postgres]`
- Lint/format: `ruff`

---

## File structure produced by Plan 1

```
apt/
├── docker-compose.yml
├── .env.example
├── pyproject.toml
├── ruff.toml
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
├── apps/
│   ├── api/
│   │   ├── __init__.py
│   │   └── main.py                    # FastAPI app, /health
│   ├── workers/
│   │   ├── __init__.py
│   │   ├── celery_app.py              # Celery + beat schedule
│   │   └── tasks/
│   │       ├── __init__.py
│   │       ├── scrape.py              # scrape:olx:<category>
│   │       ├── enrich.py              # enrich:listings:pending
│   │       ├── dedup.py               # dedup_listing()
│   │       ├── recheck.py             # recheck:listings:active
│   │       └── purge.py               # purge:listings:dead
│   └── shared/
│       ├── __init__.py
│       ├── config.py                  # pydantic-settings
│       ├── db.py                      # engine + session
│       ├── models.py                  # SQLAlchemy models
│       ├── enums.py                   # OlxCategory, ListingState, SearchType
│       ├── llm/
│       │   ├── __init__.py
│       │   └── gemini.py              # Gemini client (LLM + embeddings)
│       ├── geo/
│       │   ├── __init__.py
│       │   └── yandex.py              # Yandex geocode + routing client (cached)
│       ├── scraping/
│       │   ├── __init__.py
│       │   ├── ua_pool.py             # User-Agent + cookie rotation
│       │   ├── olx_client.py          # httpx + selectolax for olx.uz
│       │   ├── olx_parser.py          # pure parsing functions (testable)
│       │   ├── playwright_phone.py    # Playwright phone-reveal worker
│       │   └── health.py              # success-rate tracker, fallback decision
│       ├── enrichment/
│       │   ├── __init__.py
│       │   ├── language.py            # language detection
│       │   ├── translate.py           # Gemini translate
│       │   ├── currency.py            # CBU rate + UZS normalization
│       │   ├── classify.py            # LLM structured classification
│       │   ├── images.py              # download + pHash
│       │   ├── risk.py                # risk score heuristic
│       │   └── embed.py               # embedding generation
│       ├── dedup/
│       │   ├── __init__.py
│       │   └── tiered.py              # phone/pHash → address+price → cosine
│       ├── phone.py                   # normalization + sha256 hash helpers
│       └── timeutils.py               # tz helpers
└── tests/
    ├── conftest.py                    # db fixture (testcontainers), respx fixtures
    ├── fixtures/
    │   ├── olx_list_long_term.html
    │   ├── olx_list_rooms.html
    │   ├── olx_detail_owner.html
    │   ├── olx_detail_agent.html
    │   ├── cbu_rate.json
    │   ├── gemini_classify_owner.json
    │   ├── gemini_classify_agent.json
    │   └── yandex_geocode_yunusabad.json
    ├── unit/
    │   ├── test_phone.py
    │   ├── test_currency.py
    │   ├── test_language.py
    │   ├── test_olx_parser_list.py
    │   ├── test_olx_parser_detail.py
    │   ├── test_phash.py
    │   ├── test_risk.py
    │   ├── test_dedup_tiered.py
    │   ├── test_geocode_cache.py
    │   ├── test_health_monitor.py
    │   └── test_ua_pool.py
    └── integration/
        ├── test_enrich_pipeline.py
        ├── test_listing_lifecycle.py
        └── test_scrape_pipeline.py
```

---

## Phase 0 — Project scaffolding

### Task 1: Initialize repo + dependency manifest

**Files:**
- Create: `pyproject.toml`, `ruff.toml`, `.gitignore`, `.env.example`, `README.md`

- [ ] **Step 1: Initialize git + uv project**

```bash
cd /home/maurilar/petties/apt
git init
echo "# Scout" > README.md
uv init --no-readme --no-package
```

- [ ] **Step 2: Write `pyproject.toml` with all Plan 1 dependencies**

```toml
[project]
name = "scout"
version = "0.0.1"
description = "AI apartment hunter for Tashkent"
requires-python = ">=3.12,<3.13"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "aiogram>=3.13",
  "celery[redis]>=5.4",
  "redis>=5.2",
  "sqlalchemy>=2.0",
  "alembic>=1.13",
  "psycopg[binary]>=3.2",
  "pgvector>=0.3",
  "httpx>=0.28",
  "selectolax>=0.3.27",
  "playwright>=1.49",
  "pillow>=11",
  "imagehash>=4.3",
  "pydantic>=2.10",
  "pydantic-settings>=2.6",
  "tenacity>=9",
  "python-dotenv>=1.0",
  "google-genai>=0.3",
]

[dependency-groups]
dev = [
  "pytest>=8",
  "pytest-asyncio>=0.24",
  "respx>=0.21",
  "testcontainers[postgres]>=4.8",
  "ruff>=0.7",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 3: Write `ruff.toml`**

```toml
line-length = 100
target-version = "py312"

[lint]
select = ["E", "F", "W", "I", "B", "UP", "RUF"]
ignore = ["E501"]
```

- [ ] **Step 4: Write `.gitignore`**

```gitignore
__pycache__/
*.pyc
.venv/
.env
.env.local
.pytest_cache/
.ruff_cache/
*.egg-info/
dist/
build/
data/
images/
```

- [ ] **Step 5: Write `.env.example`**

```dotenv
ENV=dev

# Postgres
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=scout
POSTGRES_USER=scout
POSTGRES_PASSWORD=scout

# Redis
REDIS_URL=redis://redis:6379/0

# Gemini
GOOGLE_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
GEMINI_EMBED_MODEL=text-embedding-004

# Yandex Maps
YANDEX_GEOCODE_API_KEY=
YANDEX_ROUTING_API_KEY=

# Image storage (local volume mount)
IMAGE_STORAGE_DIR=/data/images

# Scraping
OLX_BASE_URL=https://www.olx.uz
SCRAPE_HTTPX_FAILURE_THRESHOLD=0.20
SCRAPE_PROXY_URL=

# Enrichment
ENRICHMENT_WORKERS=4
EMBEDDING_DIM=768
```

- [ ] **Step 6: Install + commit**

```bash
uv sync --all-groups
uv run python -c "import fastapi; import sqlalchemy; print('ok')"
git add .
git commit -m "chore: scaffold pyproject + ruff + env template"
```

---

### Task 2: docker-compose for local dev

**Files:**
- Create: `docker-compose.yml`, `Dockerfile`

- [ ] **Step 1: Write `Dockerfile`**

```dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev || uv sync --no-dev

COPY . .

RUN uv run playwright install --with-deps chromium

ENV PATH="/app/.venv/bin:$PATH"
```

- [ ] **Step 2: Write `docker-compose.yml`**

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 5s
      timeout: 3s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s

  api:
    build: .
    command: uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload
    env_file: .env
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  worker:
    build: .
    command: celery -A apps.workers.celery_app worker --loglevel=INFO --concurrency=4
    env_file: .env
    volumes:
      - imgdata:/data/images
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  beat:
    build: .
    command: celery -A apps.workers.celery_app beat --loglevel=INFO
    env_file: .env
    depends_on:
      - worker

volumes:
  pgdata:
  imgdata:
```

- [ ] **Step 3: Bring it up + verify Postgres has pgvector**

```bash
cp .env.example .env
docker compose up -d postgres redis
docker compose exec postgres psql -U scout -d scout -c "CREATE EXTENSION IF NOT EXISTS vector; SELECT extname FROM pg_extension;"
```
Expected output includes `vector`.

- [ ] **Step 4: Commit**

```bash
git add Dockerfile docker-compose.yml
git commit -m "chore: docker-compose with postgres+pgvector, redis, api, worker, beat"
```

---

### Task 3: Config module (`apps/shared/config.py`)

**Files:**
- Create: `apps/shared/__init__.py`, `apps/shared/config.py`
- Create: `tests/__init__.py`, `tests/conftest.py` (skeleton), `tests/unit/__init__.py`, `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing test `tests/unit/test_config.py`**

```python
import os
from apps.shared.config import settings, Settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("POSTGRES_HOST", "db.example")
    monkeypatch.setenv("POSTGRES_PORT", "6543")
    monkeypatch.setenv("POSTGRES_DB", "x")
    monkeypatch.setenv("POSTGRES_USER", "u")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p")
    monkeypatch.setenv("REDIS_URL", "redis://r:1/0")
    monkeypatch.setenv("GOOGLE_API_KEY", "g")
    monkeypatch.setenv("YANDEX_GEOCODE_API_KEY", "y1")
    monkeypatch.setenv("YANDEX_ROUTING_API_KEY", "y2")

    s = Settings()
    assert s.postgres_dsn == "postgresql+psycopg://u:p@db.example:6543/x"
    assert s.redis_url == "redis://r:1/0"
    assert s.embedding_dim == 768
```

- [ ] **Step 2: Run, expect failure**

```bash
uv run pytest tests/unit/test_config.py -v
```
Expected: ImportError or AttributeError.

- [ ] **Step 3: Write `apps/shared/config.py`**

```python
from functools import cached_property
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    env: str = "dev"

    postgres_host: str
    postgres_port: int = 5432
    postgres_db: str
    postgres_user: str
    postgres_password: str

    redis_url: str

    google_api_key: str
    gemini_model: str = "gemini-2.5-flash"
    gemini_embed_model: str = "text-embedding-004"
    embedding_dim: int = 768

    yandex_geocode_api_key: str
    yandex_routing_api_key: str

    image_storage_dir: str = "/data/images"

    olx_base_url: str = "https://www.olx.uz"
    scrape_httpx_failure_threshold: float = 0.20
    scrape_proxy_url: str = ""

    enrichment_workers: int = 4

    @cached_property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()  # type: ignore[call-arg]
```

- [ ] **Step 4: Run, expect pass**

```bash
uv run pytest tests/unit/test_config.py -v
```

- [ ] **Step 5: Commit**

```bash
git add apps/shared/__init__.py apps/shared/config.py tests/
git commit -m "feat(config): pydantic-settings module + test"
```

---

### Task 4: SQLAlchemy session factory (`apps/shared/db.py`)

**Files:**
- Create: `apps/shared/db.py`
- Create: `tests/unit/test_db.py`
- Create: `tests/conftest.py` (testcontainers postgres fixture)

- [ ] **Step 1: Write `tests/conftest.py`**

```python
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def pg_container():
    with PostgresContainer("pgvector/pgvector:pg16") as c:
        yield c


@pytest.fixture(scope="session")
def engine(pg_container):
    eng = create_engine(pg_container.get_connection_url().replace("psycopg2", "psycopg"))
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    yield eng
    eng.dispose()


@pytest.fixture
def db_session(engine) -> Session:
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()
```

- [ ] **Step 2: Write `tests/unit/test_db.py`**

```python
from sqlalchemy import text
from apps.shared.db import build_engine


def test_build_engine_connects(pg_container):
    eng = build_engine(pg_container.get_connection_url().replace("psycopg2", "psycopg"))
    with eng.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1
```

- [ ] **Step 3: Run, expect failure (`build_engine` not defined)**

```bash
uv run pytest tests/unit/test_db.py -v
```

- [ ] **Step 4: Write `apps/shared/db.py`**

```python
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from apps.shared.config import settings


def build_engine(dsn: str | None = None) -> Engine:
    return create_engine(
        dsn or settings.postgres_dsn,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )


_engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None


def init_engine() -> None:
    global _engine, SessionLocal
    _engine = build_engine()
    SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    if SessionLocal is None:
        init_engine()
    assert SessionLocal is not None
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
```

- [ ] **Step 5: Run, expect pass**

```bash
uv run pytest tests/unit/test_db.py -v
```

- [ ] **Step 6: Commit**

```bash
git add apps/shared/db.py tests/conftest.py tests/unit/test_db.py
git commit -m "feat(db): SQLAlchemy session factory + testcontainers fixture"
```

---

### Task 5: FastAPI `/health` endpoint

**Files:**
- Create: `apps/api/__init__.py`, `apps/api/main.py`
- Create: `tests/unit/test_api_health.py`

- [ ] **Step 1: Write `tests/unit/test_api_health.py`**

```python
from fastapi.testclient import TestClient
from apps.api.main import app


def test_health_returns_ok():
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}
```

- [ ] **Step 2: Run, expect failure**

```bash
uv run pytest tests/unit/test_api_health.py -v
```

- [ ] **Step 3: Write `apps/api/main.py`**

```python
from fastapi import FastAPI

app = FastAPI(title="Scout API", version="0.0.1")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: Run, expect pass**

```bash
uv run pytest tests/unit/test_api_health.py -v
```

- [ ] **Step 5: Commit**

```bash
git add apps/api/ tests/unit/test_api_health.py
git commit -m "feat(api): minimal FastAPI app with /health"
```

---

### Task 6: Celery app skeleton

**Files:**
- Create: `apps/workers/__init__.py`, `apps/workers/celery_app.py`, `apps/workers/tasks/__init__.py`
- Create: `tests/unit/test_celery_smoke.py`

- [ ] **Step 1: Write `apps/workers/celery_app.py`**

```python
from celery import Celery
from celery.schedules import crontab

from apps.shared.config import settings

app = Celery(
    "scout",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "apps.workers.tasks.scrape",
        "apps.workers.tasks.enrich",
        "apps.workers.tasks.recheck",
        "apps.workers.tasks.purge",
    ],
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Tashkent",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# Beat schedule wired progressively in later tasks; placeholder dict for now.
app.conf.beat_schedule = {}
```

- [ ] **Step 2: Write `apps/workers/tasks/__init__.py`**

```python
# package marker
```

- [ ] **Step 3: Write trivial smoke test `tests/unit/test_celery_smoke.py`**

```python
from apps.workers.celery_app import app


def test_celery_app_configured():
    assert app.main == "scout"
    assert app.conf.timezone == "Asia/Tashkent"
```

- [ ] **Step 4: Run, expect pass**

```bash
uv run pytest tests/unit/test_celery_smoke.py -v
```

- [ ] **Step 5: Commit**

```bash
git add apps/workers/ tests/unit/test_celery_smoke.py
git commit -m "feat(workers): Celery app skeleton"
```

---

## Phase 1 — DB schema + Alembic

### Task 7: Enums + base model file (`apps/shared/enums.py`, `apps/shared/models.py`)

**Files:**
- Create: `apps/shared/enums.py`
- Create: `apps/shared/models.py`

- [ ] **Step 1: Write `apps/shared/enums.py`**

```python
from enum import StrEnum


class OlxCategory(StrEnum):
    LONG_TERM = "long_term_apt"        # Долгосрочная аренда квартир
    ROOMS = "rooms"                    # Аренда комнат
    DAILY = "daily"                    # Посуточно (only if user opts in)
    LOOKING_FOR = "looking_for"        # "Сниму"


class ListingState(StrEnum):
    PENDING_ENRICH = "pending_enrich"
    ACTIVE = "active"
    DEAD = "dead"


class SearchType(StrEnum):
    WHOLE_APT_FAMILY = "whole_apt_family"
    WHOLE_APT_SOLO = "whole_apt_solo"
    SHARED_ROOM = "shared_room"
    LOOKING_FOR_ROOMMATE = "looking_for_roommate"


class GenderConstraint(StrEnum):
    ANY = "any"
    MALE = "male"
    FEMALE = "female"


class BathroomType(StrEnum):
    PRIVATE = "private"
    SHARED = "shared"
    UNKNOWN = "unknown"


class PosterRole(StrEnum):
    OWNER = "owner"
    AGENT = "agent"
    UNKNOWN = "unknown"
```

- [ ] **Step 2: Write `apps/shared/models.py` (Listing only — users/matches deferred)**

```python
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from apps.shared.config import settings
from apps.shared.enums import (
    BathroomType,
    GenderConstraint,
    ListingState,
    OlxCategory,
    PosterRole,
    SearchType,
)


class Base(DeclarativeBase):
    pass


class Listing(Base):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    source: Mapped[str] = mapped_column(String(32), default="olx")
    source_url: Mapped[str] = mapped_column(Text, unique=True)
    source_listing_id: Mapped[str] = mapped_column(String(64), index=True)
    source_category: Mapped[str] = mapped_column(String(32))  # OlxCategory

    # raw + normalized text
    title: Mapped[str] = mapped_column(Text)
    description_raw: Mapped[str] = mapped_column(Text)
    description_ru: Mapped[str | None] = mapped_column(Text)
    language_detected: Mapped[str | None] = mapped_column(String(8))
    summary_one_line: Mapped[str | None] = mapped_column(Text)

    # price
    price_raw: Mapped[str | None] = mapped_column(String(64))
    currency_raw: Mapped[str | None] = mapped_column(String(8))
    price_uzs: Mapped[int | None] = mapped_column(BigInteger, index=True)

    # structured fields (LLM-extracted or directly parsed)
    rooms: Mapped[int | None] = mapped_column(Integer, index=True)
    floor: Mapped[int | None] = mapped_column(Integer)
    total_floors: Mapped[int | None] = mapped_column(Integer)
    is_first_floor: Mapped[bool | None] = mapped_column(Boolean)
    bathroom_type: Mapped[str | None] = mapped_column(String(16))
    is_furnished: Mapped[bool | None] = mapped_column(Boolean)
    has_parking: Mapped[bool | None] = mapped_column(Boolean)

    search_type_listing: Mapped[str | None] = mapped_column(String(32))
    gender_constraint_listing: Mapped[str | None] = mapped_column(String(8))

    poster_role: Mapped[str | None] = mapped_column(String(8))
    agent_fee_text: Mapped[str | None] = mapped_column(Text)

    # location
    area: Mapped[str | None] = mapped_column(String(64), index=True)  # tuman name
    location_text: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)

    # contact
    contact_phone_raw: Mapped[str | None] = mapped_column(String(32))
    phone_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    poster_id: Mapped[str | None] = mapped_column(String(64), index=True)

    # images
    image_urls: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    image_phashes: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list)

    # vector
    embedding: Mapped[list[float] | None] = mapped_column(Vector(settings.embedding_dim))

    # risk + state
    risk_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    suppressed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    risk_flags: Mapped[dict] = mapped_column(JSONB, default=dict)

    state: Mapped[str] = mapped_column(String(20), default=ListingState.PENDING_ENRICH, index=True)

    # dedup linkage (set when this row is collapsed into a canonical one)
    canonical_listing_id: Mapped[int | None] = mapped_column(
        BigInteger, index=True
    )

    # lifecycle timestamps
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dead_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    body_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_listings_state_active", "state", postgresql_where="state = 'active'"),
        Index("ix_listings_phone_hash_alive", "phone_hash", postgresql_where="state != 'dead'"),
        UniqueConstraint("source_url", name="uq_listings_source_url"),
    )


class GeocodeCache(Base):
    __tablename__ = "geocode_cache"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    query_norm: Mapped[str] = mapped_column(Text, unique=True, index=True)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    matched_text: Mapped[str | None] = mapped_column(Text)
    raw_response: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CurrencyRate(Base):
    __tablename__ = "currency_rates"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(8), index=True)
    rate_uzs: Mapped[float] = mapped_column(Float)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("code", "fetched_at", name="uq_rate_code_at"),
    )


class ScrapeRunHealth(Base):
    """Rolling per-category counter for httpx success rate."""
    __tablename__ = "scrape_run_health"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    success_count: Mapped[int] = mapped_column(Integer)
    failure_count: Mapped[int] = mapped_column(Integer)
    used_playwright_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
```

- [ ] **Step 3: Commit**

```bash
git add apps/shared/enums.py apps/shared/models.py
git commit -m "feat(db): SQLAlchemy models for listings + caches"
```

---

### Task 8: Alembic init + initial migration

**Files:**
- Create: `alembic.ini`, `alembic/env.py`, `alembic/versions/0001_init.py`

- [ ] **Step 1: Initialize Alembic**

```bash
uv run alembic init alembic
```

- [ ] **Step 2: Edit `alembic.ini` — replace the `sqlalchemy.url` line**

```ini
sqlalchemy.url = driver://user:pass@host/db
```

becomes:

```ini
# overridden in env.py from settings
sqlalchemy.url =
```

- [ ] **Step 3: Replace `alembic/env.py`**

```python
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool, text
from alembic import context

from apps.shared.config import settings
from apps.shared.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.postgres_dsn)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
```

- [ ] **Step 4: Generate first migration**

```bash
docker compose up -d postgres
uv run alembic revision --autogenerate -m "init listings + caches"
```

- [ ] **Step 5: Inspect generated file in `alembic/versions/`** and ensure it includes:
  - `op.execute("CREATE EXTENSION IF NOT EXISTS vector")` at the top of `upgrade()` (add manually if not present)
  - All four tables: `listings`, `geocode_cache`, `currency_rates`, `scrape_run_health`
  - The two partial indexes on `listings`

- [ ] **Step 6: Apply migration**

```bash
uv run alembic upgrade head
docker compose exec postgres psql -U scout -d scout -c "\dt"
```
Expected: lists all four tables.

- [ ] **Step 7: Smoke test — round-trip a Listing row**

Create `tests/integration/__init__.py` and `tests/integration/test_listing_round_trip.py`:

```python
from datetime import datetime, timezone
from sqlalchemy.orm import sessionmaker

from apps.shared.models import Base, Listing
from apps.shared.enums import ListingState


def test_insert_and_query_listing(engine):
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    s = SessionLocal()

    row = Listing(
        source="olx",
        source_url="https://www.olx.uz/d/obyavlenie/test-1",
        source_listing_id="test-1",
        source_category="long_term_apt",
        title="2-комн. в Юнусабаде",
        description_raw="...",
        state=ListingState.PENDING_ENRICH,
        last_seen_at=datetime.now(timezone.utc),
        image_urls=[],
        image_phashes=[],
    )
    s.add(row)
    s.commit()

    fetched = s.query(Listing).filter_by(source_listing_id="test-1").one()
    assert fetched.title == "2-комн. в Юнусабаде"
    s.close()
```

```bash
uv run pytest tests/integration/test_listing_round_trip.py -v
```

- [ ] **Step 8: Commit**

```bash
git add alembic.ini alembic/ tests/integration/
git commit -m "feat(db): alembic init + first migration + round-trip test"
```

---

## Phase 2 — Scraping (httpx tier + Playwright phone reveal)

### Task 9: Phone normalization + hash (`apps/shared/phone.py`)

**Files:**
- Create: `apps/shared/phone.py`
- Create: `tests/unit/test_phone.py`

- [ ] **Step 1: Write `tests/unit/test_phone.py`**

```python
from apps.shared.phone import normalize_phone, hash_phone


def test_normalize_uz_phone_variants():
    assert normalize_phone("+998 90 123 45 67") == "998901234567"
    assert normalize_phone("90-123-45-67") == "998901234567"
    assert normalize_phone("(90) 123 45 67") == "998901234567"
    assert normalize_phone("998901234567") == "998901234567"
    assert normalize_phone("8 90 123 45 67") == "998901234567"


def test_normalize_returns_none_on_garbage():
    assert normalize_phone("") is None
    assert normalize_phone("call me") is None
    assert normalize_phone("123") is None  # too short


def test_hash_phone_is_stable_and_hex():
    assert hash_phone("998901234567") == hash_phone("998901234567")
    h = hash_phone("998901234567")
    assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)
```

- [ ] **Step 2: Run, expect failure**

```bash
uv run pytest tests/unit/test_phone.py -v
```

- [ ] **Step 3: Write `apps/shared/phone.py`**

```python
import hashlib
import re

_DIGITS_ONLY = re.compile(r"\D+")


def normalize_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = _DIGITS_ONLY.sub("", raw)
    if not digits:
        return None
    # Common UZ prefixes:
    if digits.startswith("998"):
        pass
    elif digits.startswith("8") and len(digits) == 10:
        digits = "998" + digits[1:]
    elif len(digits) == 9:
        digits = "998" + digits
    if len(digits) != 12 or not digits.startswith("998"):
        return None
    return digits


def hash_phone(normalized: str) -> str:
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run, expect pass**

```bash
uv run pytest tests/unit/test_phone.py -v
```

- [ ] **Step 5: Commit**

```bash
git add apps/shared/phone.py tests/unit/test_phone.py
git commit -m "feat(phone): UZ phone normalization + sha256 hash"
```

---

### Task 10: User-Agent pool (`apps/shared/scraping/ua_pool.py`)

**Files:**
- Create: `apps/shared/scraping/__init__.py`, `apps/shared/scraping/ua_pool.py`
- Create: `tests/unit/test_ua_pool.py`

- [ ] **Step 1: Write `tests/unit/test_ua_pool.py`**

```python
from apps.shared.scraping.ua_pool import UAPool


def test_ua_pool_rotates():
    pool = UAPool(["A", "B", "C"])
    seen = {pool.next() for _ in range(20)}
    assert seen == {"A", "B", "C"}


def test_ua_pool_default_has_modern_chrome():
    pool = UAPool()
    ua = pool.next()
    assert "Mozilla" in ua and "Chrome" in ua
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Write `apps/shared/scraping/ua_pool.py`**

```python
import random


_DEFAULT_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
]


class UAPool:
    def __init__(self, uas: list[str] | None = None) -> None:
        self._uas = uas or _DEFAULT_UAS

    def next(self) -> str:
        return random.choice(self._uas)
```

- [ ] **Step 4: Run, expect pass**

- [ ] **Step 5: Commit**

```bash
git add apps/shared/scraping/ tests/unit/test_ua_pool.py
git commit -m "feat(scraping): rotating UA pool"
```

---

### Task 11: OLX list-page parser (`apps/shared/scraping/olx_parser.py`)

**Files:**
- Create: `apps/shared/scraping/olx_parser.py`
- Create: `tests/fixtures/olx_list_long_term.html` (capture once from real page)
- Create: `tests/unit/test_olx_parser_list.py`

- [ ] **Step 1: Capture an OLX list-page HTML to `tests/fixtures/olx_list_long_term.html`**

```bash
mkdir -p tests/fixtures
curl -sL -A "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36" \
  "https://www.olx.uz/nedvizhimost/dolgosrochnaya-arenda-kvartir/tashkent/" \
  > tests/fixtures/olx_list_long_term.html
test -s tests/fixtures/olx_list_long_term.html && echo "captured $(wc -c < tests/fixtures/olx_list_long_term.html) bytes"
```

If OLX returns a Cloudflare interstitial, capture from a browser instead: open DevTools → Network → save the document response as `olx_list_long_term.html`.

- [ ] **Step 2: Write `tests/unit/test_olx_parser_list.py`**

```python
from pathlib import Path
from apps.shared.scraping.olx_parser import parse_list_page


FIXTURE = Path(__file__).parent.parent / "fixtures" / "olx_list_long_term.html"


def test_parse_list_extracts_at_least_one_card():
    html = FIXTURE.read_text(encoding="utf-8")
    cards = parse_list_page(html)
    assert len(cards) >= 1
    first = cards[0]
    assert first.url.startswith("https://www.olx.uz/")
    assert first.source_listing_id  # non-empty string
    assert first.title


def test_parse_list_card_has_price_or_none():
    html = FIXTURE.read_text(encoding="utf-8")
    cards = parse_list_page(html)
    # at least one card has a parseable price; some may have "договорная" / no price
    parseable = [c for c in cards if c.price_raw is not None]
    assert len(parseable) >= 1
```

- [ ] **Step 3: Run, expect failure**

- [ ] **Step 4: Write `apps/shared/scraping/olx_parser.py`** (the parser; keys may need tweaking once the fixture is captured — adjust selectors as needed)

```python
from dataclasses import dataclass
from urllib.parse import urljoin

from selectolax.parser import HTMLParser


OLX_BASE = "https://www.olx.uz"


@dataclass(frozen=True)
class ListCard:
    source_listing_id: str
    url: str
    title: str
    price_raw: str | None
    location_text: str | None
    posted_at_text: str | None


def parse_list_page(html: str) -> list[ListCard]:
    """Parse an OLX category list page into cards.

    Selectors are chosen against the current OLX DOM. They are intentionally
    flexible: we look for any anchor whose href matches /d/obyavlenie/ and treat
    each as one ad card, then walk siblings for price/title/location.
    """
    tree = HTMLParser(html)
    cards: list[ListCard] = []
    seen_urls: set[str] = set()

    for a in tree.css('a[href*="/d/obyavlenie/"]'):
        href = a.attributes.get("href") or ""
        if not href:
            continue
        url = urljoin(OLX_BASE, href.split("?")[0])
        if url in seen_urls:
            continue
        seen_urls.add(url)

        # source_listing_id from the trailing -ID-IDxxxxx slug
        source_listing_id = url.rstrip("/").split("-ID")[-1] if "-ID" in url else url.rsplit("/", 1)[-1]

        title = (a.text(strip=True) or "").strip()

        # walk up to the card container, then look for price/location nodes
        container = a
        for _ in range(4):
            if container.parent is None:
                break
            container = container.parent

        price_raw = _first_text(container, ['[data-testid="ad-price"]', "p.css-uj7mm0", "p[data-testid*=price]"])
        location_text = _first_text(container, ['[data-testid="location-date"]', "p.css-1a4brun", "p[data-testid*=location]"])
        posted_at_text = location_text  # OLX usually packs both into one node; refined later by detail page

        cards.append(
            ListCard(
                source_listing_id=source_listing_id,
                url=url,
                title=title,
                price_raw=price_raw,
                location_text=location_text,
                posted_at_text=posted_at_text,
            )
        )
    return cards


def _first_text(node, selectors: list[str]) -> str | None:
    for sel in selectors:
        found = node.css_first(sel)
        if found:
            txt = found.text(strip=True)
            if txt:
                return txt
    return None
```

- [ ] **Step 5: Run; if a selector mismatch occurs, inspect the fixture and adjust the selectors. Iterate until tests pass.**

```bash
uv run pytest tests/unit/test_olx_parser_list.py -v
```

- [ ] **Step 6: Commit**

```bash
git add apps/shared/scraping/olx_parser.py tests/unit/test_olx_parser_list.py tests/fixtures/olx_list_long_term.html
git commit -m "feat(scraping): OLX list-page parser + fixture test"
```

---

### Task 12: OLX detail-page parser

**Files:**
- Modify: `apps/shared/scraping/olx_parser.py`
- Create: `tests/fixtures/olx_detail_owner.html`, `tests/fixtures/olx_detail_agent.html`
- Create: `tests/unit/test_olx_parser_detail.py`

- [ ] **Step 1: Capture two real detail pages (one owner-listed, one agent-listed) into the fixtures dir**

```bash
# pick an owner-listed URL from the list fixture
curl -sL -A "Mozilla/5.0 (...)" "<owner-listing-url>" > tests/fixtures/olx_detail_owner.html
curl -sL -A "Mozilla/5.0 (...)" "<agent-listing-url>" > tests/fixtures/olx_detail_agent.html
```

- [ ] **Step 2: Write `tests/unit/test_olx_parser_detail.py`**

```python
from pathlib import Path
from apps.shared.scraping.olx_parser import parse_detail_page


FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_parse_detail_owner():
    html = (FIXTURES / "olx_detail_owner.html").read_text(encoding="utf-8")
    d = parse_detail_page(html)
    assert d.title
    assert d.description_raw
    assert d.location_text
    assert d.images  # at least one image URL
    # poster_role can be unknown; agent-flag detection happens in classify step


def test_parse_detail_agent_keywords_in_description():
    html = (FIXTURES / "olx_detail_agent.html").read_text(encoding="utf-8")
    d = parse_detail_page(html)
    txt = (d.description_raw + " " + d.title).lower()
    # heuristic: agent listings often mention "посредник", "комиссия", "агент"
    assert any(kw in txt for kw in ("посредник", "комисси", "агент"))
```

- [ ] **Step 3: Run, expect failure**

- [ ] **Step 4: Extend `apps/shared/scraping/olx_parser.py`**

```python
@dataclass(frozen=True)
class DetailPage:
    source_listing_id: str | None
    url: str | None
    title: str
    description_raw: str
    price_raw: str | None
    currency_raw: str | None
    location_text: str | None
    rooms: int | None
    floor: int | None
    total_floors: int | None
    posted_at_text: str | None
    images: list[str]
    raw_phone_text: str | None  # only present if statically embedded; usually None


def parse_detail_page(html: str) -> DetailPage:
    tree = HTMLParser(html)

    title = _first_text(tree, ['h1[data-cy="ad-title"]', "h1"]) or ""

    # OLX renders description inside a div with data-testid="ad-description" or similar;
    # be permissive
    desc_node = (
        tree.css_first('[data-cy="ad_description"]')
        or tree.css_first('[data-testid="ad-description"]')
        or tree.css_first("div.css-bgzo2k")
    )
    description_raw = desc_node.text(strip=True) if desc_node else ""

    price_raw = _first_text(tree, ['[data-testid="ad-price"]', "h3.css-12vqlj3"])
    currency_raw = _detect_currency(price_raw)

    location_text = _first_text(tree, ['[data-testid="map-aside-section"]', '[data-cy="ad-posted-at"]'])

    rooms = _extract_int(_first_text(tree, ['li:contains("комнат")']))
    floor, total_floors = _extract_floor_pair(_first_text(tree, ['li:contains("этаж")']))

    posted_at_text = _first_text(tree, ['[data-cy="ad-posted-at"]'])

    images = []
    for img in tree.css('img[src*="frankfurt.apollo.olxcdn.com"]'):
        src = img.attributes.get("src") or ""
        if src and src not in images:
            images.append(src)

    # raw phone is typically NOT in static HTML — left for Playwright reveal
    raw_phone_text = None

    return DetailPage(
        source_listing_id=None,
        url=None,
        title=title,
        description_raw=description_raw,
        price_raw=price_raw,
        currency_raw=currency_raw,
        location_text=location_text,
        rooms=rooms,
        floor=floor,
        total_floors=total_floors,
        posted_at_text=posted_at_text,
        images=images,
        raw_phone_text=raw_phone_text,
    )


def _detect_currency(price_raw: str | None) -> str | None:
    if not price_raw:
        return None
    p = price_raw.lower()
    if "$" in p or "y.e" in p or "у.е" in p or "usd" in p:
        return "USD"
    if "сум" in p or "uzs" in p:
        return "UZS"
    return None


def _extract_int(text: str | None) -> int | None:
    if not text:
        return None
    m = __import__("re").search(r"\d+", text)
    return int(m.group(0)) if m else None


def _extract_floor_pair(text: str | None) -> tuple[int | None, int | None]:
    if not text:
        return (None, None)
    m = __import__("re").search(r"(\d+)\s*/\s*(\d+)", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    n = _extract_int(text)
    return (n, None)
```

- [ ] **Step 5: Run, expect pass (adjust selectors against fixtures as needed)**

```bash
uv run pytest tests/unit/test_olx_parser_detail.py -v
```

- [ ] **Step 6: Commit**

```bash
git add apps/shared/scraping/olx_parser.py tests/unit/test_olx_parser_detail.py tests/fixtures/olx_detail_*.html
git commit -m "feat(scraping): OLX detail-page parser + fixture tests"
```

---

### Task 13: OLX HTTP client (`apps/shared/scraping/olx_client.py`)

**Files:**
- Create: `apps/shared/scraping/olx_client.py`
- Create: `tests/unit/test_olx_client.py` (uses `respx`)

- [ ] **Step 1: Write `tests/unit/test_olx_client.py`**

```python
import pytest
import respx
from httpx import Response

from apps.shared.scraping.olx_client import OlxClient


@pytest.mark.asyncio
@respx.mock
async def test_fetch_list_returns_html_and_marks_success():
    respx.get("https://www.olx.uz/nedvizhimost/dolgosrochnaya-arenda-kvartir/tashkent/").mock(
        return_value=Response(200, text="<html>list</html>")
    )
    client = OlxClient()
    html, ok = await client.fetch_list("https://www.olx.uz/nedvizhimost/dolgosrochnaya-arenda-kvartir/tashkent/")
    assert ok and "<html>list" in html
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_fetch_returns_failure_on_5xx():
    respx.get("https://www.olx.uz/x").mock(return_value=Response(503, text="bad"))
    client = OlxClient()
    html, ok = await client.fetch_list("https://www.olx.uz/x")
    assert not ok
    await client.aclose()
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Write `apps/shared/scraping/olx_client.py`**

```python
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from apps.shared.config import settings
from apps.shared.scraping.ua_pool import UAPool


class OlxClient:
    def __init__(self, ua_pool: UAPool | None = None) -> None:
        self._uas = ua_pool or UAPool()
        proxies = settings.scrape_proxy_url or None
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=10.0),
            follow_redirects=True,
            proxy=proxies,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru,en;q=0.7",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _get(self, url: str) -> httpx.Response:
        return await self._client.get(url, headers={"User-Agent": self._uas.next()})

    async def fetch_list(self, url: str) -> tuple[str, bool]:
        try:
            r = await self._get(url)
        except Exception:
            return "", False
        return r.text, 200 <= r.status_code < 300

    async def fetch_detail(self, url: str) -> tuple[str, bool]:
        return await self.fetch_list(url)
```

- [ ] **Step 4: Run, expect pass**

- [ ] **Step 5: Commit**

```bash
git add apps/shared/scraping/olx_client.py tests/unit/test_olx_client.py
git commit -m "feat(scraping): async OLX client with retry"
```

---

### Task 14: Health monitor (`apps/shared/scraping/health.py`)

**Files:**
- Create: `apps/shared/scraping/health.py`
- Create: `tests/unit/test_health_monitor.py`

- [ ] **Step 1: Write `tests/unit/test_health_monitor.py`**

```python
from apps.shared.scraping.health import HealthWindow


def test_window_records_outcomes():
    w = HealthWindow(window_seconds=60)
    for _ in range(8): w.record(success=True)
    for _ in range(2): w.record(success=False)
    assert w.failure_rate() == 0.2


def test_window_should_fallback_when_failure_rate_above_threshold():
    w = HealthWindow(window_seconds=60)
    for _ in range(7): w.record(success=False)
    for _ in range(3): w.record(success=True)
    assert w.failure_rate() == 0.7
    assert w.should_fallback(threshold=0.2) is True


def test_window_does_not_fallback_with_too_few_samples():
    w = HealthWindow(window_seconds=60, min_samples=5)
    w.record(success=False)
    w.record(success=False)
    assert w.should_fallback(threshold=0.2) is False
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Write `apps/shared/scraping/health.py`**

```python
import time
from collections import deque


class HealthWindow:
    def __init__(self, window_seconds: int = 3600, min_samples: int = 10) -> None:
        self._window = window_seconds
        self._min_samples = min_samples
        self._events: deque[tuple[float, bool]] = deque()

    def _evict_old(self) -> None:
        cutoff = time.time() - self._window
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def record(self, success: bool) -> None:
        self._events.append((time.time(), success))
        self._evict_old()

    def failure_rate(self) -> float:
        self._evict_old()
        if not self._events:
            return 0.0
        f = sum(1 for _, ok in self._events if not ok)
        return f / len(self._events)

    def should_fallback(self, threshold: float = 0.20) -> bool:
        self._evict_old()
        return len(self._events) >= self._min_samples and self.failure_rate() > threshold
```

- [ ] **Step 4: Run, expect pass**

- [ ] **Step 5: Commit**

```bash
git add apps/shared/scraping/health.py tests/unit/test_health_monitor.py
git commit -m "feat(scraping): rolling health window for httpx tier"
```

---

### Task 15: Playwright phone-reveal worker (`apps/shared/scraping/playwright_phone.py`)

**Files:**
- Create: `apps/shared/scraping/playwright_phone.py`
- Create: `tests/integration/test_playwright_phone.py` (gated by env var, defaults to skip)

- [ ] **Step 1: Write `apps/shared/scraping/playwright_phone.py`**

```python
import logging

from playwright.async_api import async_playwright

from apps.shared.scraping.ua_pool import UAPool

log = logging.getLogger(__name__)


class PhoneRevealer:
    """Reveals the phone behind OLX's "Show phone" click. One-shot per listing."""

    def __init__(self) -> None:
        self._uas = UAPool()

    async def reveal(self, listing_url: str, timeout_ms: int = 20000) -> str | None:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(user_agent=self._uas.next(), locale="ru-RU")
            page = await ctx.new_page()
            try:
                await page.goto(listing_url, wait_until="domcontentloaded", timeout=timeout_ms)
                # OLX phone-reveal button — text-based selectors are most stable across redesigns
                button = page.get_by_role("button", name=lambda t: bool(t and ("Показать телефон" in t or "Show phone" in t)))
                if await button.count() == 0:
                    log.warning("phone reveal button not found on %s", listing_url)
                    return None
                await button.first.click(timeout=timeout_ms)
                # phone usually rendered inside an <a href="tel:..."> or within a span next to the button
                tel = page.locator("a[href^='tel:']").first
                await tel.wait_for(state="visible", timeout=timeout_ms)
                href = await tel.get_attribute("href")
                if href and href.startswith("tel:"):
                    return href.removeprefix("tel:").strip()
                return (await tel.inner_text()).strip() or None
            finally:
                await ctx.close()
                await browser.close()
```

- [ ] **Step 2: Write `tests/integration/test_playwright_phone.py`** (gated)

```python
import os
import pytest

from apps.shared.scraping.playwright_phone import PhoneRevealer


@pytest.mark.skipif(
    not os.getenv("RUN_PLAYWRIGHT_LIVE"),
    reason="set RUN_PLAYWRIGHT_LIVE=1 and PHONE_REVEAL_URL=<olx-listing> to run",
)
@pytest.mark.asyncio
async def test_reveal_phone_live():
    url = os.environ["PHONE_REVEAL_URL"]
    phone = await PhoneRevealer().reveal(url)
    # Sanity: contains digits, length plausible
    digits = "".join(c for c in (phone or "") if c.isdigit())
    assert len(digits) >= 9
```

- [ ] **Step 3: Install Playwright browser (one-time)**

```bash
uv run playwright install --with-deps chromium
```

- [ ] **Step 4: Run gated test against a real listing**

```bash
RUN_PLAYWRIGHT_LIVE=1 PHONE_REVEAL_URL="<paste-an-olx-listing-url>" \
  uv run pytest tests/integration/test_playwright_phone.py -v
```

- [ ] **Step 5: Commit**

```bash
git add apps/shared/scraping/playwright_phone.py tests/integration/test_playwright_phone.py
git commit -m "feat(scraping): Playwright phone-reveal worker (live-gated test)"
```

---

### Task 16: Scrape Celery task (`apps/workers/tasks/scrape.py`)

**Files:**
- Create: `apps/workers/tasks/scrape.py`
- Modify: `apps/workers/celery_app.py` (add beat schedule entries)
- Create: `tests/integration/test_scrape_pipeline.py`

- [ ] **Step 1: Write `apps/workers/tasks/scrape.py`**

```python
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from apps.shared.db import session_scope
from apps.shared.enums import ListingState, OlxCategory
from apps.shared.models import Listing, ScrapeRunHealth
from apps.shared.scraping.health import HealthWindow
from apps.shared.scraping.olx_client import OlxClient
from apps.shared.scraping.olx_parser import parse_list_page
from apps.workers.celery_app import app

log = logging.getLogger(__name__)

CATEGORY_URLS: dict[str, str] = {
    OlxCategory.LONG_TERM: "https://www.olx.uz/nedvizhimost/dolgosrochnaya-arenda-kvartir/tashkent/",
    OlxCategory.ROOMS: "https://www.olx.uz/nedvizhimost/arenda-komnat/tashkent/",
    OlxCategory.DAILY: "https://www.olx.uz/nedvizhimost/posutochno-pochasovo/tashkent/",
    OlxCategory.LOOKING_FOR: "https://www.olx.uz/nedvizhimost/snimu/tashkent/",
}

# module-level windows so the rolling counter survives across task invocations within a worker
_windows: dict[str, HealthWindow] = {}


def _window(category: str) -> HealthWindow:
    if category not in _windows:
        _windows[category] = HealthWindow(window_seconds=3600, min_samples=10)
    return _windows[category]


async def _scrape_category_async(category: str) -> dict:
    url = CATEGORY_URLS[category]
    client = OlxClient()
    try:
        html, ok = await client.fetch_list(url)
        _window(category).record(success=ok)
        if not ok:
            return {"category": category, "ok": False, "discovered": 0, "inserted": 0}

        cards = parse_list_page(html)
        inserted = 0
        with session_scope() as s:
            for c in cards:
                existing_id = s.execute(
                    select(Listing.id).where(Listing.source_url == c.url)
                ).scalar_one_or_none()
                if existing_id:
                    s.execute(
                        Listing.__table__.update()
                        .where(Listing.id == existing_id)
                        .values(last_seen_at=datetime.now(timezone.utc))
                    )
                    continue
                s.add(
                    Listing(
                        source="olx",
                        source_url=c.url,
                        source_listing_id=c.source_listing_id,
                        source_category=category,
                        title=c.title,
                        description_raw="",  # filled in detail-pass
                        price_raw=c.price_raw,
                        location_text=c.location_text,
                        state=ListingState.PENDING_ENRICH,
                        last_seen_at=datetime.now(timezone.utc),
                        image_urls=[],
                        image_phashes=[],
                    )
                )
                inserted += 1

            s.add(ScrapeRunHealth(
                category=category,
                success_count=1 if ok else 0,
                failure_count=0 if ok else 1,
                used_playwright_fallback=False,
            ))
        return {"category": category, "ok": True, "discovered": len(cards), "inserted": inserted}
    finally:
        await client.aclose()


@app.task(name="scrape.olx.category", bind=True, max_retries=3, default_retry_delay=60)
def scrape_olx_category(self, category: str) -> dict:
    log.info("scrape:olx:%s starting", category)
    return asyncio.run(_scrape_category_async(category))


@app.task(name="scrape.olx.detail", bind=True, max_retries=3, default_retry_delay=60)
def scrape_olx_detail(self, listing_id: int) -> dict:
    return asyncio.run(_scrape_detail_async(listing_id))


async def _scrape_detail_async(listing_id: int) -> dict:
    from apps.shared.scraping.olx_parser import parse_detail_page
    client = OlxClient()
    try:
        with session_scope() as s:
            row = s.get(Listing, listing_id)
            if row is None:
                return {"ok": False, "reason": "not found"}
            html, ok = await client.fetch_detail(row.source_url)
            if not ok:
                return {"ok": False, "reason": "fetch failed"}
            d = parse_detail_page(html)
            row.title = d.title or row.title
            row.description_raw = d.description_raw or row.description_raw
            row.price_raw = d.price_raw or row.price_raw
            row.currency_raw = d.currency_raw or row.currency_raw
            row.location_text = d.location_text or row.location_text
            row.rooms = d.rooms or row.rooms
            row.floor = d.floor or row.floor
            row.total_floors = d.total_floors or row.total_floors
            row.image_urls = d.images or row.image_urls
            row.last_seen_at = datetime.now(timezone.utc)
            return {"ok": True, "listing_id": listing_id}
    finally:
        await client.aclose()
```

- [ ] **Step 2: Add beat schedule in `apps/workers/celery_app.py`**

Replace the placeholder `beat_schedule = {}` with:

```python
from celery.schedules import crontab

app.conf.beat_schedule = {
    "scrape-long-term": {
        "task": "scrape.olx.category",
        "schedule": 300,  # 5 min
        "args": ("long_term_apt",),
    },
    "scrape-rooms": {
        "task": "scrape.olx.category",
        "schedule": 300,
        "args": ("rooms",),
    },
    "scrape-looking-for": {
        "task": "scrape.olx.category",
        "schedule": 300,
        "args": ("looking_for",),
    },
    # daily category disabled by default; enable per user demand later
}
```

- [ ] **Step 3: Smoke test scrape end-to-end against the live site**

```bash
docker compose up -d postgres redis
docker compose up worker beat
# in another terminal:
docker compose exec worker python -c "
from apps.workers.tasks.scrape import scrape_olx_category
print(scrape_olx_category.apply(args=('long_term_apt',)).get())
"
```
Expected: `{'category': 'long_term_apt', 'ok': True, 'discovered': N, 'inserted': M}` with N≥20.

- [ ] **Step 4: Verify rows in DB**

```bash
docker compose exec postgres psql -U scout -d scout -c \
  "SELECT count(*), state FROM listings GROUP BY state;"
```
Expected: > 20 rows in `pending_enrich`.

- [ ] **Step 5: Commit**

```bash
git add apps/workers/
git commit -m "feat(scrape): list-page Celery task + beat schedule (every 5min)"
```

---

## Phase 3 — Enrichment

### Task 17: Gemini client (`apps/shared/llm/gemini.py`)

**Files:**
- Create: `apps/shared/llm/__init__.py`, `apps/shared/llm/gemini.py`
- Create: `tests/unit/test_gemini_client.py` (mocks the SDK)

- [ ] **Step 1: Write `apps/shared/llm/gemini.py`**

```python
import json
from typing import Any

from google import genai
from tenacity import retry, stop_after_attempt, wait_exponential

from apps.shared.config import settings


class GeminiClient:
    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.google_api_key)
        self._model = settings.gemini_model
        self._embed_model = settings.gemini_embed_model

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(min=1, max=10), reraise=True)
    def generate_json(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        """Call Gemini with structured-output mode and parse the JSON response."""
        resp = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": schema,
                "temperature": 0.1,
            },
        )
        return json.loads(resp.text)

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(min=1, max=10), reraise=True)
    def translate_to_ru(self, text: str) -> str:
        prompt = (
            "Translate the following apartment listing text to Russian. "
            "Preserve numbers, addresses, and proper nouns. Output ONLY the translation, no commentary.\n\n"
            f"---\n{text}\n---"
        )
        resp = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config={"temperature": 0.0},
        )
        return resp.text.strip()

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(min=1, max=10), reraise=True)
    def embed(self, text: str) -> list[float]:
        resp = self._client.models.embed_content(
            model=self._embed_model,
            contents=text,
        )
        # google-genai returns either single or list of embeddings depending on input shape
        emb = resp.embeddings[0]
        return list(emb.values)
```

- [ ] **Step 2: Write `tests/unit/test_gemini_client.py`** (mock at SDK boundary)

```python
from unittest.mock import MagicMock, patch

from apps.shared.llm.gemini import GeminiClient


@patch("apps.shared.llm.gemini.genai.Client")
def test_generate_json_parses_response(MockClient):
    inst = MockClient.return_value
    fake = MagicMock()
    fake.text = '{"x": 1, "y": "z"}'
    inst.models.generate_content.return_value = fake

    c = GeminiClient()
    out = c.generate_json("anything", schema={"type": "object"})
    assert out == {"x": 1, "y": "z"}


@patch("apps.shared.llm.gemini.genai.Client")
def test_translate_strips_whitespace(MockClient):
    inst = MockClient.return_value
    fake = MagicMock()
    fake.text = "  Привет!\n"
    inst.models.generate_content.return_value = fake

    c = GeminiClient()
    assert c.translate_to_ru("Hello!") == "Привет!"
```

- [ ] **Step 3: Run, expect pass**

- [ ] **Step 4: Commit**

```bash
git add apps/shared/llm/ tests/unit/test_gemini_client.py
git commit -m "feat(llm): Gemini client (generate_json, translate, embed)"
```

---

### Task 18: Language detection (`apps/shared/enrichment/language.py`)

**Files:**
- Create: `apps/shared/enrichment/__init__.py`, `apps/shared/enrichment/language.py`
- Create: `tests/unit/test_language.py`

- [ ] **Step 1: Write `tests/unit/test_language.py`**

```python
from apps.shared.enrichment.language import detect_language


def test_detects_russian():
    assert detect_language("Двухкомнатная квартира в центре, мебель есть.") == "ru"


def test_detects_uzbek_latin():
    txt = "Ikki xonali kvartira shahar markazida, mebel bilan."
    assert detect_language(txt) == "uz-latn"


def test_detects_uzbek_cyrillic():
    txt = "Икки хонали квартира марказда, мебель билан."
    assert detect_language(txt) == "uz-cyrl"


def test_short_text_falls_back_to_unknown_or_ru():
    assert detect_language("ok") in ("unknown", "ru")
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Write `apps/shared/enrichment/language.py`**

```python
import re

# Uzbek-Latin morpheme markers (orthography + common rental words)
_UZ_LATN_HINTS = re.compile(
    r"[oʻgʻ’ʼ]|\b(xonali|kvartira|ijara(?:ga)?|markaz(?:da|ida)?|mebel|uy|narx)\b",
    re.IGNORECASE,
)
# Uzbek-Cyrillic morpheme markers (the Cyrillic letters ў/қ/ҳ/ғ are exclusive to Uzbek/etc, not Russian;
# plus typical rental/grammar words)
_UZ_CYRL_HINTS = re.compile(
    r"[ўқҳғ]|\b(хонали|ижара(?:га)?|узатилади|ижарага|марказ(?:да|ида)?|мебелсиз|нархи)\b",
    re.IGNORECASE,
)


def detect_language(text: str) -> str:
    """Returns one of: 'ru', 'uz-latn', 'uz-cyrl', 'unknown'."""
    if not text or len(text) < 6:
        return "unknown"

    has_cyrillic = bool(re.search(r"[Ѐ-ӿ]", text))
    has_latin = bool(re.search(r"[A-Za-z]", text))

    if has_cyrillic and not has_latin:
        return "uz-cyrl" if _UZ_CYRL_HINTS.search(text) else "ru"

    if has_latin and not has_cyrillic:
        # In Tashkent OLX domain, Latin-only listings are overwhelmingly Uzbek-Latin (rarely English).
        return "uz-latn" if _UZ_LATN_HINTS.search(text) else "uz-latn"

    if has_cyrillic and has_latin:
        # Mixed: prefer Uzbek hint if any, otherwise dominant-script.
        if _UZ_CYRL_HINTS.search(text):
            return "uz-cyrl"
        if _UZ_LATN_HINTS.search(text):
            return "uz-latn"
        cyr = len(re.findall(r"[Ѐ-ӿ]", text))
        lat = len(re.findall(r"[A-Za-z]", text))
        return "ru" if cyr >= lat else "uz-latn"

    return "unknown"
```

Note: `langdetect` is not used. Reliable Russian-vs-Uzbek-Cyrillic discrimination isn't a real feature in any general langid library; cheap regex morpheme markers outperform it for our short-text rental domain.

- [ ] **Step 4: Run, expect pass**

- [ ] **Step 5: Commit**

```bash
git add apps/shared/enrichment/ tests/unit/test_language.py
git commit -m "feat(enrichment): language detection (ru / uz-latn / uz-cyrl)"
```

---

### Task 19: Translate to RU (`apps/shared/enrichment/translate.py`)

**Files:**
- Create: `apps/shared/enrichment/translate.py`
- Create: `tests/unit/test_translate.py`

- [ ] **Step 1: Write `tests/unit/test_translate.py`**

```python
from unittest.mock import MagicMock

from apps.shared.enrichment.translate import ensure_ru


def test_returns_text_as_is_when_already_ru():
    out = ensure_ru("Двухкомнатная квартира.", language="ru", llm=None)
    assert out == "Двухкомнатная квартира."


def test_calls_llm_for_uz_latn():
    llm = MagicMock()
    llm.translate_to_ru.return_value = "Двухкомнатная квартира."
    out = ensure_ru("Ikki xonali kvartira.", language="uz-latn", llm=llm)
    assert out == "Двухкомнатная квартира."
    llm.translate_to_ru.assert_called_once()


def test_short_text_skips_llm():
    llm = MagicMock()
    out = ensure_ru("ok", language="uz-latn", llm=llm)
    assert out == "ok"
    llm.translate_to_ru.assert_not_called()
```

- [ ] **Step 2: Write `apps/shared/enrichment/translate.py`**

```python
def ensure_ru(text: str, *, language: str, llm) -> str:
    if not text or len(text) < 8:
        return text
    if language == "ru":
        return text
    if language in ("uz-latn", "uz-cyrl"):
        return llm.translate_to_ru(text)
    return text
```

- [ ] **Step 3: Run, expect pass**

- [ ] **Step 4: Commit**

```bash
git add apps/shared/enrichment/translate.py tests/unit/test_translate.py
git commit -m "feat(enrichment): translate-to-ru gated by language"
```

---

### Task 20: Currency normalization (`apps/shared/enrichment/currency.py`)

**Files:**
- Create: `apps/shared/enrichment/currency.py`
- Create: `tests/fixtures/cbu_rate.json` (sample CBU response)
- Create: `tests/unit/test_currency.py`

- [ ] **Step 1: Capture a real CBU rate JSON to `tests/fixtures/cbu_rate.json`**

```bash
curl -sL "https://cbu.uz/uz/arkhiv-kursov-valyut/json/USD/" | head -c 4000 > tests/fixtures/cbu_rate.json
```

- [ ] **Step 2: Write `tests/unit/test_currency.py`**

```python
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import respx
from httpx import Response
from datetime import datetime, timezone

from apps.shared.enrichment.currency import (
    parse_price_text,
    fetch_cbu_usd_to_uzs,
    convert_to_uzs,
)


def test_parse_price_uzs():
    p, c = parse_price_text("8 000 000 сум")
    assert p == 8_000_000 and c == "UZS"


def test_parse_price_usd():
    p, c = parse_price_text("$650")
    assert p == 650 and c == "USD"


def test_parse_price_with_thousand_separators():
    p, c = parse_price_text("1 200 у.е.")
    assert p == 1200 and c == "USD"


def test_parse_price_returns_none_on_garbage():
    assert parse_price_text("договорная") == (None, None)


@respx.mock
def test_fetch_cbu_returns_float():
    fixture = Path("tests/fixtures/cbu_rate.json").read_text(encoding="utf-8")
    respx.get("https://cbu.uz/uz/arkhiv-kursov-valyut/json/USD/").mock(
        return_value=Response(200, text=fixture)
    )
    rate = fetch_cbu_usd_to_uzs()
    assert rate > 1000


def test_convert_uzs_passthrough():
    assert convert_to_uzs(1_000_000, "UZS", usd_rate=12500) == 1_000_000


def test_convert_usd_to_uzs():
    assert convert_to_uzs(500, "USD", usd_rate=12500) == 6_250_000
```

- [ ] **Step 3: Run, expect failure**

- [ ] **Step 4: Write `apps/shared/enrichment/currency.py`**

```python
import json
import re
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from apps.shared.db import session_scope
from apps.shared.models import CurrencyRate

_PRICE_NUM = re.compile(r"([\d\s  ]+)")


def parse_price_text(text: str | None) -> tuple[int | None, str | None]:
    if not text:
        return (None, None)
    t = text.lower()
    if "договор" in t:
        return (None, None)
    currency: str | None = None
    if "$" in t or "у.е" in t or "y.e" in t or "usd" in t:
        currency = "USD"
    elif "сум" in t or "uzs" in t or "so'm" in t or "soʻm" in t:
        currency = "UZS"
    m = _PRICE_NUM.search(t.replace("\xa0", " ").replace(" ", " "))
    if not m:
        return (None, currency)
    digits = re.sub(r"\D", "", m.group(1))
    if not digits:
        return (None, currency)
    return (int(digits), currency)


def fetch_cbu_usd_to_uzs() -> float:
    """Fetch and cache today's CBU USD→UZS rate. Returns rate."""
    today = datetime.now(timezone.utc).date()
    with session_scope() as s:
        row = s.execute(
            select(CurrencyRate)
            .where(CurrencyRate.code == "USD")
            .order_by(CurrencyRate.fetched_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if row and row.fetched_at.date() == today:
            return row.rate_uzs

    r = httpx.get("https://cbu.uz/uz/arkhiv-kursov-valyut/json/USD/", timeout=10.0)
    r.raise_for_status()
    data = r.json()
    rate = float(data[0]["Rate"])
    with session_scope() as s:
        s.add(CurrencyRate(code="USD", rate_uzs=rate))
    return rate


def convert_to_uzs(amount: int, currency: str, *, usd_rate: float) -> int:
    if currency == "UZS":
        return amount
    if currency == "USD":
        return int(round(amount * usd_rate))
    return amount  # unknown: passthrough
```

- [ ] **Step 5: Run, expect pass**

- [ ] **Step 6: Commit**

```bash
git add apps/shared/enrichment/currency.py tests/unit/test_currency.py tests/fixtures/cbu_rate.json
git commit -m "feat(enrichment): price parser + CBU rate fetcher + UZS conversion"
```

---

### Task 21: LLM classifier (`apps/shared/enrichment/classify.py`)

**Files:**
- Create: `apps/shared/enrichment/classify.py`
- Create: `tests/fixtures/gemini_classify_owner.json`
- Create: `tests/unit/test_classify.py`

- [ ] **Step 1: Capture a sample classifier response (or hand-write one) into `tests/fixtures/gemini_classify_owner.json`**

```json
{
  "search_type": "whole_apt_solo",
  "gender_constraint": "any",
  "is_furnished": true,
  "has_parking": false,
  "is_first_floor": false,
  "bathroom_type": "private",
  "poster_role": "owner",
  "agent_fee_text": null,
  "summary_one_line": "Двухкомнатная в Юнусабаде, с мебелью, рядом метро."
}
```

- [ ] **Step 2: Write `tests/unit/test_classify.py`**

```python
import json
from pathlib import Path
from unittest.mock import MagicMock

from apps.shared.enrichment.classify import classify_listing


def test_classify_returns_structured_fields():
    expected = json.loads(Path("tests/fixtures/gemini_classify_owner.json").read_text())
    llm = MagicMock()
    llm.generate_json.return_value = expected

    out = classify_listing(
        title="2-комн., Юнусабад",
        description_ru="Просторная двушка с мебелью...",
        llm=llm,
    )
    assert out["search_type"] == "whole_apt_solo"
    assert out["bathroom_type"] == "private"
    assert out["poster_role"] == "owner"
    llm.generate_json.assert_called_once()


def test_classify_handles_missing_optional_fields():
    llm = MagicMock()
    llm.generate_json.return_value = {
        "search_type": "shared_room",
        "gender_constraint": "female",
        "is_furnished": None,
        "has_parking": None,
        "is_first_floor": None,
        "bathroom_type": "shared",
        "poster_role": "unknown",
        "agent_fee_text": None,
        "summary_one_line": "Комната для девушки.",
    }
    out = classify_listing(title="", description_ru="комната девушке", llm=llm)
    assert out["gender_constraint"] == "female"
    assert out["is_furnished"] is None
```

- [ ] **Step 3: Write `apps/shared/enrichment/classify.py`**

```python
CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "search_type": {"type": "string", "enum": [
            "whole_apt_family", "whole_apt_solo", "shared_room", "looking_for_roommate"
        ]},
        "gender_constraint": {"type": "string", "enum": ["any", "male", "female"]},
        "is_furnished": {"type": ["boolean", "null"]},
        "has_parking": {"type": ["boolean", "null"]},
        "is_first_floor": {"type": ["boolean", "null"]},
        "bathroom_type": {"type": "string", "enum": ["private", "shared", "unknown"]},
        "poster_role": {"type": "string", "enum": ["owner", "agent", "unknown"]},
        "agent_fee_text": {"type": ["string", "null"]},
        "summary_one_line": {"type": "string"},
    },
    "required": [
        "search_type", "gender_constraint", "bathroom_type",
        "poster_role", "summary_one_line",
    ],
}


CLASSIFY_PROMPT = """\
Ты помогаешь сервису поиска квартир в Ташкенте.
Извлеки структурированные поля из объявления ниже.
Если не уверен в значении — возвращай null или "unknown".
"summary_one_line" — короткое (≤120 симв.) описание объявления на русском.

Заголовок:
{title}

Описание:
{description}
"""


def classify_listing(*, title: str, description_ru: str, llm) -> dict:
    prompt = CLASSIFY_PROMPT.format(title=title or "", description=description_ru or "")
    return llm.generate_json(prompt, schema=CLASSIFY_SCHEMA)
```

- [ ] **Step 4: Run, expect pass**

- [ ] **Step 5: Commit**

```bash
git add apps/shared/enrichment/classify.py tests/unit/test_classify.py tests/fixtures/gemini_classify_owner.json
git commit -m "feat(enrichment): LLM structured-output classifier for listings"
```

---

### Task 22: Image download + pHash (`apps/shared/enrichment/images.py`)

**Files:**
- Create: `apps/shared/enrichment/images.py`
- Create: `tests/unit/test_phash.py`
- Add: a small JPEG fixture `tests/fixtures/sample.jpg` (any small image)

- [ ] **Step 1: Drop a small JPEG into `tests/fixtures/sample.jpg`**

```bash
curl -sL https://www.gstatic.com/webp/gallery/1.jpg > tests/fixtures/sample.jpg
ls -lh tests/fixtures/sample.jpg
```

- [ ] **Step 2: Write `tests/unit/test_phash.py`**

```python
from pathlib import Path
import respx
from httpx import Response

from apps.shared.enrichment.images import compute_phash, download_and_phash


def test_compute_phash_deterministic():
    h1 = compute_phash(Path("tests/fixtures/sample.jpg").read_bytes())
    h2 = compute_phash(Path("tests/fixtures/sample.jpg").read_bytes())
    assert h1 == h2 and len(h1) == 16


@respx.mock
def test_download_and_phash(tmp_path):
    img_bytes = Path("tests/fixtures/sample.jpg").read_bytes()
    respx.get("https://example.test/img.jpg").mock(return_value=Response(200, content=img_bytes))
    saved_path, h = download_and_phash("https://example.test/img.jpg", storage_dir=str(tmp_path))
    assert saved_path.endswith(".jpg")
    assert len(h) == 16
```

- [ ] **Step 3: Write `apps/shared/enrichment/images.py`**

```python
import hashlib
import io
import os
from pathlib import Path

import httpx
import imagehash
from PIL import Image


def compute_phash(image_bytes: bytes) -> str:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    return str(imagehash.phash(img))  # 16-char hex


def download_and_phash(url: str, *, storage_dir: str, timeout: float = 15.0) -> tuple[str, str]:
    r = httpx.get(url, timeout=timeout)
    r.raise_for_status()
    content = r.content
    h_url = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    ext = Path(url.split("?")[0]).suffix.lower() or ".jpg"
    out = Path(storage_dir) / f"{h_url}{ext}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(content)
    return (str(out), compute_phash(content))
```

- [ ] **Step 4: Run, expect pass**

- [ ] **Step 5: Commit**

```bash
git add apps/shared/enrichment/images.py tests/unit/test_phash.py tests/fixtures/sample.jpg
git commit -m "feat(enrichment): image download + perceptual hash"
```

---

### Task 23: Yandex geocoder (`apps/shared/geo/yandex.py`)

**Files:**
- Create: `apps/shared/geo/__init__.py`, `apps/shared/geo/yandex.py`
- Create: `tests/fixtures/yandex_geocode_yunusabad.json`
- Create: `tests/unit/test_geocode_cache.py`

- [ ] **Step 1: Hand-write a stub Yandex response into `tests/fixtures/yandex_geocode_yunusabad.json`**

```json
{
  "response": {
    "GeoObjectCollection": {
      "featureMember": [
        {
          "GeoObject": {
            "Point": {"pos": "69.282671 41.366776"},
            "metaDataProperty": {
              "GeocoderMetaData": {"text": "Узбекистан, Ташкент, Юнусабадский район"}
            }
          }
        }
      ]
    }
  }
}
```

- [ ] **Step 2: Write `tests/unit/test_geocode_cache.py`**

```python
import json
from pathlib import Path
import respx
from httpx import Response

from apps.shared.geo.yandex import geocode


@respx.mock
def test_geocode_caches_result(db_session, monkeypatch):
    fixture = Path("tests/fixtures/yandex_geocode_yunusabad.json").read_text()
    route = respx.get("https://geocode-maps.yandex.ru/1.x/").mock(
        return_value=Response(200, text=fixture)
    )
    monkeypatch.setenv("YANDEX_GEOCODE_API_KEY", "test")

    r1 = geocode("Юнусабадский район, Ташкент")
    r2 = geocode("Юнусабадский район, Ташкент")
    assert r1.lat == r2.lat == 41.366776
    assert r1.lng == r2.lng == 69.282671
    assert route.call_count == 1  # cache hit on second call
```

- [ ] **Step 3: Write `apps/shared/geo/yandex.py`**

```python
from dataclasses import dataclass

import httpx
from sqlalchemy import select

from apps.shared.config import settings
from apps.shared.db import session_scope
from apps.shared.models import GeocodeCache


@dataclass(frozen=True)
class GeocodeResult:
    lat: float | None
    lng: float | None
    matched_text: str | None


def _normalize_query(q: str) -> str:
    return " ".join(q.lower().split())


def geocode(query: str) -> GeocodeResult:
    norm = _normalize_query(query)
    with session_scope() as s:
        row = s.execute(
            select(GeocodeCache).where(GeocodeCache.query_norm == norm)
        ).scalar_one_or_none()
        if row is not None:
            return GeocodeResult(row.lat, row.lng, row.matched_text)

    r = httpx.get(
        "https://geocode-maps.yandex.ru/1.x/",
        params={
            "apikey": settings.yandex_geocode_api_key,
            "format": "json",
            "geocode": query,
            "lang": "ru_RU",
            "results": 1,
        },
        timeout=10.0,
    )
    r.raise_for_status()
    data = r.json()
    feats = data.get("response", {}).get("GeoObjectCollection", {}).get("featureMember", [])
    if not feats:
        result = GeocodeResult(None, None, None)
    else:
        obj = feats[0]["GeoObject"]
        lng_str, lat_str = obj["Point"]["pos"].split()
        result = GeocodeResult(
            lat=float(lat_str),
            lng=float(lng_str),
            matched_text=obj["metaDataProperty"]["GeocoderMetaData"]["text"],
        )
    with session_scope() as s:
        s.add(GeocodeCache(
            query_norm=norm,
            lat=result.lat, lng=result.lng,
            matched_text=result.matched_text,
            raw_response=data,
        ))
    return result
```

- [ ] **Step 4: Run, expect pass**

- [ ] **Step 5: Commit**

```bash
git add apps/shared/geo/ tests/unit/test_geocode_cache.py tests/fixtures/yandex_geocode_yunusabad.json
git commit -m "feat(geo): Yandex geocoder with persistent cache"
```

---

### Task 24: Risk score (`apps/shared/enrichment/risk.py`)

**Files:**
- Create: `apps/shared/enrichment/risk.py`
- Create: `tests/unit/test_risk.py`

- [ ] **Step 1: Write `tests/unit/test_risk.py`**

```python
from apps.shared.enrichment.risk import compute_risk


def test_no_flags():
    score, flags = compute_risk(
        price_uzs=8_000_000,
        area_median=8_500_000,
        area_stdev=1_000_000,
        phone_seen_unrelated=0,
        cross_phash_collision=False,
        agent_keywords_present=False,
        poster_role="owner",
    )
    assert score == 0 and flags == {}


def test_low_price_flag():
    score, flags = compute_risk(
        price_uzs=4_000_000,
        area_median=8_500_000,
        area_stdev=1_000_000,
        phone_seen_unrelated=0,
        cross_phash_collision=False,
        agent_keywords_present=False,
        poster_role="owner",
    )
    assert flags["unusually_low_price"] is True
    assert score == 1


def test_phash_collision_and_agent_keywords_combine():
    score, flags = compute_risk(
        price_uzs=8_000_000,
        area_median=8_500_000,
        area_stdev=1_000_000,
        phone_seen_unrelated=5,
        cross_phash_collision=True,
        agent_keywords_present=True,
        poster_role="owner",
    )
    # phone_unrelated_count + phash_collision + agent_kw_with_owner_role
    assert flags == {
        "phone_seen_unrelated": True,
        "photo_possibly_reused": True,
        "agent_keywords_with_owner_label": True,
    }
    assert score == 3


def test_phone_unrelated_threshold():
    score, _ = compute_risk(
        price_uzs=8_000_000,
        area_median=8_500_000,
        area_stdev=1_000_000,
        phone_seen_unrelated=2,  # below default threshold of 3
        cross_phash_collision=False,
        agent_keywords_present=False,
        poster_role="owner",
    )
    assert score == 0
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Write `apps/shared/enrichment/risk.py`**

```python
PHONE_UNRELATED_THRESHOLD = 3


def compute_risk(
    *,
    price_uzs: int | None,
    area_median: int | None,
    area_stdev: int | None,
    phone_seen_unrelated: int,
    cross_phash_collision: bool,
    agent_keywords_present: bool,
    poster_role: str,
) -> tuple[int, dict]:
    flags: dict[str, bool] = {}
    if (
        price_uzs is not None and area_median is not None and area_stdev is not None
        and price_uzs < (area_median - 2 * area_stdev)
    ):
        flags["unusually_low_price"] = True
    if phone_seen_unrelated >= PHONE_UNRELATED_THRESHOLD:
        flags["phone_seen_unrelated"] = True
    if cross_phash_collision:
        flags["photo_possibly_reused"] = True
    if agent_keywords_present and poster_role == "owner":
        flags["agent_keywords_with_owner_label"] = True
    return (sum(flags.values()), flags)
```

- [ ] **Step 4: Run, expect pass**

- [ ] **Step 5: Commit**

```bash
git add apps/shared/enrichment/risk.py tests/unit/test_risk.py
git commit -m "feat(enrichment): heuristic risk scorer"
```

---

### Task 25: Embedding generation (`apps/shared/enrichment/embed.py`)

**Files:**
- Create: `apps/shared/enrichment/embed.py`
- Create: `tests/unit/test_embed.py`

- [ ] **Step 1: Write `tests/unit/test_embed.py`**

```python
from unittest.mock import MagicMock

from apps.shared.enrichment.embed import build_listing_embedding_text, embed_listing


def test_text_includes_title_and_summary():
    txt = build_listing_embedding_text(
        title="2-комн., Юнусабад",
        description_ru="Просторная двушка с мебелью.",
        summary_one_line="Двушка с мебелью.",
        rooms=2, area="Yunusabad", price_uzs=8_000_000,
        is_furnished=True, has_parking=False, bathroom_type="private",
    )
    assert "2-комн., Юнусабад" in txt
    assert "Просторная" in txt
    assert "rooms=2" in txt
    assert "furnished" in txt


def test_embed_listing_calls_llm():
    llm = MagicMock()
    llm.embed.return_value = [0.1] * 768
    out = embed_listing("any text", llm=llm)
    assert len(out) == 768
    llm.embed.assert_called_once_with("any text")
```

- [ ] **Step 2: Write `apps/shared/enrichment/embed.py`**

```python
def build_listing_embedding_text(
    *,
    title: str,
    description_ru: str,
    summary_one_line: str | None,
    rooms: int | None,
    area: str | None,
    price_uzs: int | None,
    is_furnished: bool | None,
    has_parking: bool | None,
    bathroom_type: str | None,
) -> str:
    parts = [title, description_ru, summary_one_line or ""]
    structured = []
    if rooms is not None:
        structured.append(f"rooms={rooms}")
    if area:
        structured.append(f"area={area}")
    if price_uzs is not None:
        structured.append(f"price_uzs={price_uzs}")
    if is_furnished:
        structured.append("furnished")
    if has_parking:
        structured.append("parking")
    if bathroom_type and bathroom_type != "unknown":
        structured.append(f"bathroom={bathroom_type}")
    parts.append(" ".join(structured))
    return "\n".join(p for p in parts if p)


def embed_listing(text: str, *, llm) -> list[float]:
    return llm.embed(text)
```

- [ ] **Step 3: Run, expect pass**

- [ ] **Step 4: Commit**

```bash
git add apps/shared/enrichment/embed.py tests/unit/test_embed.py
git commit -m "feat(enrichment): embedding text builder + Gemini embed call"
```

---

### Task 26: Enrichment orchestrator task (`apps/workers/tasks/enrich.py`)

**Files:**
- Create: `apps/workers/tasks/enrich.py`
- Modify: `apps/workers/celery_app.py` (add beat entry)
- Create: `tests/integration/test_enrich_pipeline.py`

- [ ] **Step 1: Write `apps/workers/tasks/enrich.py`**

```python
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from apps.shared.config import settings
from apps.shared.db import session_scope
from apps.shared.enrichment import currency, embed, images, language, risk, translate
from apps.shared.enrichment.classify import classify_listing
from apps.shared.enums import ListingState, PosterRole
from apps.shared.geo.yandex import geocode
from apps.shared.llm.gemini import GeminiClient
from apps.shared.models import Listing
from apps.shared.phone import hash_phone, normalize_phone
from apps.shared.scraping.playwright_phone import PhoneRevealer
from apps.workers.celery_app import app

log = logging.getLogger(__name__)

AGENT_KEYWORDS = ("посредник", "комисси", "агент", "vositachi", "agent", "broker")


def _enrich_one(listing_id: int) -> dict:
    llm = GeminiClient()
    with session_scope() as s:
        row = s.get(Listing, listing_id)
        if row is None or row.state != ListingState.PENDING_ENRICH:
            return {"ok": False, "reason": "not pending"}

        # 1. language
        lang = language.detect_language(f"{row.title}\n{row.description_raw}")
        # 2. translate to ru
        row.description_ru = translate.ensure_ru(
            row.description_raw, language=lang, llm=llm
        )
        row.language_detected = lang

        # 3. currency normalization
        if row.price_raw and row.price_uzs is None:
            amt, cur = currency.parse_price_text(row.price_raw)
            if amt and cur == "USD":
                rate = currency.fetch_cbu_usd_to_uzs()
                row.price_uzs = currency.convert_to_uzs(amt, "USD", usd_rate=rate)
                row.currency_raw = "USD"
            elif amt and cur == "UZS":
                row.price_uzs = amt
                row.currency_raw = "UZS"

        # 4. LLM classify
        classification = classify_listing(
            title=row.title, description_ru=row.description_ru or "", llm=llm
        )
        row.search_type_listing = classification["search_type"]
        row.gender_constraint_listing = classification["gender_constraint"]
        row.is_furnished = classification.get("is_furnished")
        row.has_parking = classification.get("has_parking")
        row.is_first_floor = classification.get("is_first_floor")
        row.bathroom_type = classification.get("bathroom_type")
        row.poster_role = classification.get("poster_role", PosterRole.UNKNOWN)
        row.agent_fee_text = classification.get("agent_fee_text")
        row.summary_one_line = classification.get("summary_one_line")

        # 5. images + pHash
        phashes: list[str] = []
        for url in row.image_urls or []:
            try:
                _, h = images.download_and_phash(url, storage_dir=settings.image_storage_dir)
                phashes.append(h)
            except Exception as e:  # noqa: BLE001
                log.warning("image download failed for %s: %s", url, e)
        row.image_phashes = phashes

        # 6. geocode
        if row.location_text:
            g = geocode(row.location_text + ", Ташкент")
            row.lat, row.lng = g.lat, g.lng

        # 7. phone reveal (Playwright) — only if not already known
        if not row.contact_phone_raw:
            try:
                import asyncio
                phone_raw = asyncio.run(PhoneRevealer().reveal(row.source_url))
            except Exception as e:  # noqa: BLE001
                log.warning("phone reveal failed for %s: %s", row.source_url, e)
                phone_raw = None
            if phone_raw:
                normalized = normalize_phone(phone_raw)
                row.contact_phone_raw = phone_raw
                row.phone_hash = hash_phone(normalized) if normalized else None

        # 8. risk score
        agent_kw = any(kw in (row.description_ru or "").lower() for kw in AGENT_KEYWORDS)
        # phone_seen_unrelated count: distinct listings with same phone_hash
        from sqlalchemy import func
        phone_seen_unrelated = 0
        if row.phone_hash:
            phone_seen_unrelated = s.execute(
                select(func.count(Listing.id)).where(
                    Listing.phone_hash == row.phone_hash,
                    Listing.id != row.id,
                )
            ).scalar_one()
        # cross-phash collision: any other listing shares any of our phashes with a different phone_hash
        cross_collision = False
        if phashes and row.phone_hash:
            cross_collision = bool(
                s.execute(
                    select(Listing.id).where(
                        Listing.image_phashes.overlap(phashes),
                        Listing.phone_hash != row.phone_hash,
                        Listing.id != row.id,
                    ).limit(1)
                ).first()
            )

        # area median + stdev placeholders — Plan 1 leaves these None until we have enough data
        area_median = None
        area_stdev = None
        score, flags = risk.compute_risk(
            price_uzs=row.price_uzs,
            area_median=area_median,
            area_stdev=area_stdev,
            phone_seen_unrelated=phone_seen_unrelated,
            cross_phash_collision=cross_collision,
            agent_keywords_present=agent_kw,
            poster_role=row.poster_role or PosterRole.UNKNOWN,
        )
        row.risk_score = score
        row.risk_flags = flags
        row.suppressed = score >= 3  # HARD threshold; soft warnings come from flags

        # 9. embed
        emb_text = embed.build_listing_embedding_text(
            title=row.title,
            description_ru=row.description_ru or "",
            summary_one_line=row.summary_one_line,
            rooms=row.rooms,
            area=row.area,
            price_uzs=row.price_uzs,
            is_furnished=row.is_furnished,
            has_parking=row.has_parking,
            bathroom_type=row.bathroom_type,
        )
        row.embedding = embed.embed_listing(emb_text, llm=llm)

        # 10. flip state
        row.state = ListingState.ACTIVE
        row.enriched_at = datetime.now(timezone.utc)

    return {"ok": True, "listing_id": listing_id}


@app.task(name="enrich.listing", bind=True, max_retries=3, default_retry_delay=120)
def enrich_listing(self, listing_id: int) -> dict:
    return _enrich_one(listing_id)


@app.task(name="enrich.listings.pending")
def enrich_pending_listings(batch_size: int = 50) -> dict:
    """Find pending listings and dispatch one enrich task per row."""
    with session_scope() as s:
        ids = s.execute(
            select(Listing.id)
            .where(Listing.state == ListingState.PENDING_ENRICH)
            .order_by(Listing.created_at.asc())
            .limit(batch_size)
        ).scalars().all()
    for lid in ids:
        enrich_listing.delay(lid)
    return {"dispatched": len(ids)}
```

- [ ] **Step 2: Add to beat schedule (`apps/workers/celery_app.py`)**

```python
app.conf.beat_schedule.update({
    "enrich-pending": {
        "task": "enrich.listings.pending",
        "schedule": 60,  # every minute
        "args": (),
    },
})
```

- [ ] **Step 3: Smoke test against the seeded DB**

```bash
docker compose up -d worker beat
docker compose exec worker python -c "
from apps.workers.tasks.enrich import enrich_pending_listings
print(enrich_pending_listings.apply().get())
"
docker compose exec postgres psql -U scout -d scout -c \
  "SELECT count(*) FILTER (WHERE state='active'), count(*) FILTER (WHERE suppressed) FROM listings;"
```

- [ ] **Step 4: Commit**

```bash
git add apps/workers/tasks/enrich.py apps/workers/celery_app.py
git commit -m "feat(enrich): orchestrator task running full enrichment pipeline"
```

---

## Phase 4 — Deduplication

### Task 27: Tiered dedup (`apps/shared/dedup/tiered.py`)

**Files:**
- Create: `apps/shared/dedup/__init__.py`, `apps/shared/dedup/tiered.py`
- Create: `tests/unit/test_dedup_tiered.py`

- [ ] **Step 1: Write `tests/unit/test_dedup_tiered.py`**

```python
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import sessionmaker

from apps.shared.dedup.tiered import find_canonical_for, dedup_decide
from apps.shared.enums import ListingState
from apps.shared.models import Base, Listing


def _mk(s, **kw):
    defaults = dict(
        source="olx", source_listing_id=kw.get("source_listing_id", "x"),
        source_category="long_term_apt",
        title="t", description_raw="", state=ListingState.ACTIVE,
        last_seen_at=datetime.now(timezone.utc),
        image_urls=[], image_phashes=[],
    )
    defaults.update(kw)
    row = Listing(**defaults)
    s.add(row); s.flush()
    return row


def test_phone_match_finds_canonical(engine):
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    a = _mk(s, source_url="https://www.olx.uz/a", source_listing_id="a", phone_hash="h1", price_uzs=8_000_000, rooms=2, area="Yunusabad")
    b = _mk(s, source_url="https://www.olx.uz/b", source_listing_id="b", phone_hash="h1", price_uzs=8_000_000, rooms=2, area="Yunusabad")
    s.commit()

    canonical = find_canonical_for(s, b)
    assert canonical is not None and canonical.id == a.id


def test_address_price_rooms_match_finds_canonical(engine):
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    a = _mk(s, source_url="https://www.olx.uz/c", source_listing_id="c", location_text="ул. Лабзак, 10", price_uzs=8_000_000, rooms=2, area="Yunusabad")
    b = _mk(s, source_url="https://www.olx.uz/d", source_listing_id="d", location_text="Лабзак 10", price_uzs=8_100_000, rooms=2, area="Yunusabad")
    s.commit()

    canonical = find_canonical_for(s, b)
    assert canonical is not None and canonical.id == a.id


def test_no_match_returns_none(engine):
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    a = _mk(s, source_url="https://www.olx.uz/e", source_listing_id="e", phone_hash="h2", price_uzs=8_000_000, rooms=2, area="Yunusabad")
    b = _mk(s, source_url="https://www.olx.uz/f", source_listing_id="f", phone_hash="h3", price_uzs=12_000_000, rooms=4, area="Chilanzar")
    s.commit()

    assert find_canonical_for(s, b) is None
```

- [ ] **Step 2: Write `apps/shared/dedup/tiered.py`**

```python
import re
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.shared.models import Listing


_NON_ALNUM = re.compile(r"[^\wа-яёҳқғўa-z0-9]+", re.IGNORECASE)


def _normalize_address(s: str | None) -> str:
    if not s:
        return ""
    return _NON_ALNUM.sub(" ", s.lower()).strip()


def find_canonical_for(session: Session, candidate: Listing) -> Listing | None:
    """Return an existing Listing that should be the canonical for `candidate`, or None."""
    # Tier 1: phone match OR pHash exact match
    if candidate.phone_hash:
        row = session.execute(
            select(Listing)
            .where(
                Listing.phone_hash == candidate.phone_hash,
                Listing.id != candidate.id,
                Listing.state != "dead",
                Listing.canonical_listing_id.is_(None),
            )
            .order_by(Listing.created_at.asc())
            .limit(1)
        ).scalar_one_or_none()
        if row:
            return row

    if candidate.image_phashes:
        row = session.execute(
            select(Listing)
            .where(
                Listing.image_phashes.overlap(candidate.image_phashes),
                Listing.id != candidate.id,
                Listing.state != "dead",
                Listing.canonical_listing_id.is_(None),
            )
            .order_by(Listing.created_at.asc())
            .limit(1)
        ).scalar_one_or_none()
        if row:
            return row

    # Tier 2: address + price (±5%) + rooms
    if candidate.location_text and candidate.price_uzs and candidate.rooms:
        addr_norm = _normalize_address(candidate.location_text)
        if addr_norm:
            lo = int(candidate.price_uzs * 0.95)
            hi = int(candidate.price_uzs * 1.05)
            rows = session.execute(
                select(Listing).where(
                    Listing.id != candidate.id,
                    Listing.state != "dead",
                    Listing.canonical_listing_id.is_(None),
                    Listing.rooms == candidate.rooms,
                    Listing.price_uzs.between(lo, hi),
                    Listing.area == candidate.area if candidate.area else True,
                )
            ).scalars().all()
            for r in rows:
                if _normalize_address(r.location_text) == addr_norm:
                    return r

    # Tier 3 (cosine) is intentionally deferred — pgvector kNN is added once we have inventory volume.
    return None


def dedup_decide(session: Session, candidate: Listing) -> Listing | None:
    """Sets candidate.canonical_listing_id if a canonical is found. Returns the canonical (or None)."""
    canonical = find_canonical_for(session, candidate)
    if canonical:
        candidate.canonical_listing_id = canonical.id
    return canonical
```

- [ ] **Step 3: Run, expect pass**

- [ ] **Step 4: Commit**

```bash
git add apps/shared/dedup/ tests/unit/test_dedup_tiered.py
git commit -m "feat(dedup): tiered dedup (phone/pHash → address+price+rooms)"
```

---

### Task 28: Wire dedup into the enrichment task

**Files:**
- Modify: `apps/workers/tasks/enrich.py`

- [ ] **Step 1: Add the dedup call at the end of `_enrich_one`** (just before `row.state = ListingState.ACTIVE`):

```python
        from apps.shared.dedup.tiered import dedup_decide
        dedup_decide(s, row)
```

- [ ] **Step 2: Commit**

```bash
git add apps/workers/tasks/enrich.py
git commit -m "feat(enrich): run dedup at end of enrichment pipeline"
```

---

## Phase 5 — Listing lifecycle

### Task 29: Recheck task (`apps/workers/tasks/recheck.py`)

**Files:**
- Create: `apps/workers/tasks/recheck.py`
- Modify: `apps/workers/celery_app.py`
- Create: `tests/integration/test_listing_lifecycle.py`

- [ ] **Step 1: Write `apps/workers/tasks/recheck.py`**

```python
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from apps.shared.db import session_scope
from apps.shared.enums import ListingState
from apps.shared.models import Listing
from apps.shared.scraping.olx_client import OlxClient
from apps.workers.celery_app import app

log = logging.getLogger(__name__)

DEAD_KEYWORDS = ("объявление снято", "ad removed", "404")


async def _recheck_async(batch_size: int = 200) -> dict:
    client = OlxClient()
    flipped = 0
    try:
        with session_scope() as s:
            ids_urls = s.execute(
                select(Listing.id, Listing.source_url).where(
                    Listing.state == ListingState.ACTIVE
                ).limit(batch_size)
            ).all()
            for lid, url in ids_urls:
                html, ok = await client.fetch_detail(url)
                is_dead = (not ok) or any(k in html.lower() for k in DEAD_KEYWORDS)
                if is_dead:
                    s.execute(
                        Listing.__table__.update()
                        .where(Listing.id == lid)
                        .values(state=ListingState.DEAD, dead_at=datetime.now(timezone.utc))
                    )
                    flipped += 1
                else:
                    s.execute(
                        Listing.__table__.update()
                        .where(Listing.id == lid)
                        .values(last_seen_at=datetime.now(timezone.utc))
                    )
        return {"checked": len(ids_urls), "flipped_dead": flipped}
    finally:
        await client.aclose()


@app.task(name="recheck.listings.active")
def recheck_active(batch_size: int = 200) -> dict:
    return asyncio.run(_recheck_async(batch_size=batch_size))
```

- [ ] **Step 2: Add beat entry for daily recheck**

```python
from celery.schedules import crontab
app.conf.beat_schedule["recheck-active"] = {
    "task": "recheck.listings.active",
    "schedule": crontab(hour=3, minute=0),  # daily 03:00 UTC
}
```

- [ ] **Step 3: Smoke test**

```bash
docker compose exec worker python -c "
from apps.workers.tasks.recheck import recheck_active
print(recheck_active.apply().get())
"
```

- [ ] **Step 4: Commit**

```bash
git add apps/workers/tasks/recheck.py apps/workers/celery_app.py
git commit -m "feat(lifecycle): daily recheck task flips dead listings"
```

---

### Task 30: Purge job (`apps/workers/tasks/purge.py`)

**Files:**
- Create: `apps/workers/tasks/purge.py`
- Modify: `apps/workers/celery_app.py`

- [ ] **Step 1: Write `apps/workers/tasks/purge.py`**

```python
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from apps.shared.db import session_scope
from apps.shared.enums import ListingState
from apps.shared.models import Listing
from apps.workers.celery_app import app

log = logging.getLogger(__name__)


@app.task(name="purge.listings.dead")
def purge_dead_listing_bodies(older_than_days: int = 60) -> dict:
    """Strip raw body + raw phone from listings dead for > N days. pHash + phone_hash retained."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    with session_scope() as s:
        result = s.execute(
            update(Listing)
            .where(
                Listing.state == ListingState.DEAD,
                Listing.dead_at < cutoff,
                Listing.body_purged_at.is_(None),
            )
            .values(
                description_raw="",
                description_ru=None,
                contact_phone_raw=None,
                summary_one_line=None,
                body_purged_at=datetime.now(timezone.utc),
            )
        )
        return {"purged": result.rowcount}
```

- [ ] **Step 2: Add beat entry**

```python
app.conf.beat_schedule["purge-dead-bodies"] = {
    "task": "purge.listings.dead",
    "schedule": crontab(hour=4, minute=30),  # daily 04:30 UTC
}
```

- [ ] **Step 3: Commit**

```bash
git add apps/workers/tasks/purge.py apps/workers/celery_app.py
git commit -m "feat(lifecycle): daily body-purge job for dead listings"
```

---

## Phase 6 — End-to-end integration test

### Task 31: E2E pipeline integration test

**Files:**
- Create: `tests/integration/test_e2e_pipeline.py`

- [ ] **Step 1: Write the test that uses the cached list-page fixture and a mocked Gemini**

```python
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import respx
from httpx import Response
from sqlalchemy.orm import sessionmaker

from apps.shared.enums import ListingState
from apps.shared.models import Base, Listing
from apps.workers.tasks.enrich import _enrich_one


@respx.mock
def test_enrich_one_full_pipeline(engine, monkeypatch):
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    # seed a pending listing manually (skip the scrape step in this test)
    s = SessionLocal()
    detail_html = Path("tests/fixtures/olx_detail_owner.html").read_text(encoding="utf-8")
    classification = json.loads(Path("tests/fixtures/gemini_classify_owner.json").read_text())
    geo_fixture = Path("tests/fixtures/yandex_geocode_yunusabad.json").read_text()

    row = Listing(
        source="olx",
        source_url="https://www.olx.uz/d/obyavlenie/test-1",
        source_listing_id="test-1",
        source_category="long_term_apt",
        title="2-комн. в Юнусабаде",
        description_raw="Просторная двушка с мебелью, рядом метро Юнусабад.",
        price_raw="$650",
        location_text="Юнусабадский район",
        state=ListingState.PENDING_ENRICH,
        last_seen_at=datetime.now(timezone.utc),
        image_urls=[],
        image_phashes=[],
    )
    s.add(row); s.commit()
    listing_id = row.id
    s.close()

    # mock external HTTP
    respx.get("https://geocode-maps.yandex.ru/1.x/").mock(return_value=Response(200, text=geo_fixture))
    respx.get("https://cbu.uz/uz/arkhiv-kursov-valyut/json/USD/").mock(
        return_value=Response(200, json=[{"Rate": "12500.0"}])
    )

    # mock Gemini at the SDK boundary
    with patch("apps.shared.llm.gemini.genai.Client") as MockClient, \
         patch("apps.shared.scraping.playwright_phone.async_playwright"):
        inst = MockClient.return_value
        # generate_content returns either translation, classification JSON, or summary;
        # one-call-per-method: we mock generate_content to return classification JSON,
        # translate_to_ru is bypassed because language detection will be 'ru'.
        inst.models.generate_content.return_value.text = json.dumps(classification)
        inst.models.embed_content.return_value.embeddings = [type("E", (), {"values": [0.1] * 768})()]

        out = _enrich_one(listing_id)

    assert out["ok"] is True

    s = SessionLocal()
    final = s.get(Listing, listing_id)
    assert final.state == ListingState.ACTIVE
    assert final.search_type_listing == classification["search_type"]
    assert final.price_uzs == 8_125_000  # 650 * 12500
    assert final.lat is not None
    assert final.embedding is not None
    s.close()
```

- [ ] **Step 2: Run, expect pass**

```bash
uv run pytest tests/integration/test_e2e_pipeline.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_e2e_pipeline.py
git commit -m "test(e2e): full enrichment pipeline integration test"
```

---

### Task 32: Live smoke against production OLX (manual gate)

- [ ] **Step 1: Bring up the full stack with a real `.env`**

```bash
# fill GOOGLE_API_KEY, YANDEX_GEOCODE_API_KEY, YANDEX_ROUTING_API_KEY in .env
docker compose up -d
```

- [ ] **Step 2: Trigger one full cycle manually**

```bash
docker compose exec worker python -c "
from apps.workers.tasks.scrape import scrape_olx_category
from apps.workers.tasks.enrich import enrich_pending_listings
print('scrape:', scrape_olx_category.apply(args=('long_term_apt',)).get())
print('enrich dispatch:', enrich_pending_listings.apply(args=(20,)).get())
"
sleep 60
docker compose exec postgres psql -U scout -d scout -c "
SELECT
  count(*) FILTER (WHERE state='pending_enrich') AS pending,
  count(*) FILTER (WHERE state='active' AND NOT suppressed) AS active_clean,
  count(*) FILTER (WHERE suppressed) AS suppressed,
  count(*) FILTER (WHERE canonical_listing_id IS NOT NULL) AS deduped
FROM listings;
"
```

- [ ] **Step 3: Eyeball one enriched row**

```bash
docker compose exec postgres psql -U scout -d scout -c "
SELECT id, title, area, price_uzs, search_type_listing, poster_role, risk_score, risk_flags
FROM listings WHERE state='active' ORDER BY id DESC LIMIT 5;
"
```

- [ ] **Step 4: Sign off — Plan 1 is complete when:**

  - `scrape_olx_category('long_term_apt')` populates ≥ 20 rows in one run
  - `enrich_pending_listings(20)` flips ≥ 18 of them to `active` (≥ 90% success rate)
  - At least one row has `risk_score > 0` and `risk_flags` non-empty (sanity check on heuristics)
  - At least one row has `canonical_listing_id` set (dedup is wired)
  - All unit + integration tests pass: `uv run pytest -v`
  - Beat is running and the schedule fires automatically (let it run 15 min, watch logs)

- [ ] **Step 5: Tag the milestone**

```bash
git tag plan-1-foundation-ingestion
```

---

## Self-review notes

- **Spec coverage:** Plan 1 implements §3 (enums, listings table; tuman list is data, deferred to Plan 2 onboarding), §3.1 implicitly (no user-facing area picker yet — covered by `Listing.area` field), §5 (scraping + enrichment + dedup + lifecycle) in full, §8 (privacy: phone purge wired in Task 30), §10 data model partial (Listing + caches; users/matches in Plans 2 & 3).
- **Out of Plan 1 scope:** `users` table, `matches` table, bot, ranking, digests, KPI funnel, `top_1pct_threshold`, area median/stdev (passed as `None` to risk scorer for now — refined in Plan 3 once we have aggregate stats).
- **Open questions surfaced for the executing engineer:**
  - OLX's exact CSS selectors change occasionally; the parser tasks anticipate this with permissive selectors and a fixture-driven test loop. If selectors fail against fresh HTML, capture a new fixture and adjust.
  - Phone reveal: `PhoneRevealer` may need per-user-account credentials if OLX starts requiring login. The test is gated; revisit if anti-bot tightens.
  - Risk-score thresholds are bare integers (1, 3) for MVP. Expect to tune after real-data feedback.

