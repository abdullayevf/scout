# Scout

> AI-powered apartment hunting bot for Tashkent — scrapes OLX.uz, enriches with LLMs + vector embeddings, and delivers personalised Telegram alerts that get smarter with every reaction.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-336791?style=flat-square&logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-7-DC382D?style=flat-square&logo=redis&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-5-37814A?style=flat-square&logo=celery&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-aiogram_3-26A5E4?style=flat-square&logo=telegram&logoColor=white)
![Gemini](https://img.shields.io/badge/Google-Gemini_2.5-4285F4?style=flat-square&logo=google&logoColor=white)

---

## What it does

Scout monitors OLX.uz every 5 minutes, runs each listing through a multi-stage enrichment pipeline (translation → LLM classification → geocoding → 3072-d embedding → image perceptual hashing → deduplication), then scores it against every active user's preference profile using a 7-component model.

Top-1% matches trigger an **instant Telegram alert** (capped at 3/day, respects quiet hours). Every morning at 09:00 Tashkent time, users receive a **digest of the 8 best picks**. Each 👍 / 👎 / 📞 reaction updates the user's preference embedding in real time. A 48 h → 5 d KPI chase funnel tracks whether users actually contact and rent — closing the loop from discovery to move-in.

---

## Pipeline

```
OLX.uz
  │  scrape every 5 min  (httpx + Playwright fallback)
  ▼
Enrichment worker
  ├─ translate → RU          Gemini 2.5 Flash
  ├─ LLM classify            rooms · price · area · poster role · risk flags
  ├─ geocode + commute       Yandex Maps Geocoder + Routing API
  ├─ embed 3072-d            Gemini text-embedding-001
  ├─ pHash images            perceptual duplicate detection
  └─ 4-tier dedup            phone hash / pHash / address / cosine similarity
  ▼
Match fanout  (triggered on every enriched listing)
  ├─ SQL hard filters    budget · search type · seen_set · distrust_set
  ├─ Python filters      rooms · area mask · dealbreakers · keyword blacklist
  └─ 7-component score   cosine · budget · commute · freshness · rep · axes · risk
        ├─ top-1 %  →  instant Telegram alert  (≤ 3/day, quiet hours enforced)
        └─ daily 09:00  →  digest of top 8     (cold-start stratified < 10 reactions)
  ▼
User reaction   👍  👎  📞
  ├─ embedding update    pref ← normalise( (1-α)·pref + α·listing )
  ├─ preference mutations  budget tighten · area mask · distrust set
  └─ KPI chase funnel    48 h "did you contact?" → 5 d "did you rent?"
                         + Sunday weekly check-in
```

---

## Features

- **Real-time scraper** — category-level health monitoring, Playwright fallback when httpx is blocked
- **LLM enrichment** — Gemini translates and classifies every listing; one-line Russian summary generated per item
- **Vector matching** — pgvector cosine similarity over 3072-d Gemini embeddings
- **Geocoded commute scoring** — Yandex Routing API computes door-to-door travel time against user's commute origin
- **17-state onboarding FSM** — guided preference capture with per-axis editing via `/settings`
- **Online preference learning** — each reaction nudges the preference vector; specific signals (expensive, bad area, fishy) apply targeted mutations
- **Cold-start handling** — stratified picks across rooms/area until 10 reactions collected
- **KPI funnel** — 48 h contact chase, 5 d rental-outcome chase, Sunday weekly check-in, dashboard queries for like/contact/mute rates
- **60+ unit tests** — testcontainers-based pgvector fixture, TDD throughout

---

## Tech Stack

| Layer | Technology |
|---|---|
| Bot framework | [aiogram 3](https://docs.aiogram.dev/) — webhook mode, Redis FSM storage |
| Task queue | [Celery 5](https://docs.celeryq.dev/) + Redis broker, beat scheduler |
| Database | PostgreSQL 16 + [pgvector](https://github.com/pgvector/pgvector) |
| ORM / migrations | SQLAlchemy 2.x · Alembic |
| LLM / embeddings | Google Gemini 2.5 Flash · text-embedding-001 (3072-d) |
| Geocoding | Yandex Maps Geocoder · Yandex Routing API |
| Scraping | httpx · Playwright (Chromium) |
| Image dedup | Pillow · imagehash (pHash) |
| Packaging | [uv](https://github.com/astral-sh/uv) · Python 3.12 |
| Deployment | Docker Compose · nginx · Let's Encrypt |

---

## Local Development

```bash
# 1. Clone and install deps
git clone https://github.com/abdullayevf/scout.git && cd scout
cp .env.example .env   # fill in API keys

# 2. Start infrastructure
docker compose up -d postgres redis

# 3. Install Python deps and migrate
uv sync
uv run alembic upgrade head

# 4. Expose a local webhook via ngrok (Telegram requires HTTPS)
ngrok http 8080
# then set TELEGRAM_WEBHOOK_URL=https://<ngrok-id>.ngrok.io/bot/webhook in .env

# 5. Start the bot
uv run python -m apps.bot.main
```

Celery worker and beat scheduler (needed for enrichment + matching):

```bash
uv run celery -A apps.workers.celery_app worker --loglevel=INFO --concurrency=1
uv run celery -A apps.workers.celery_app beat --loglevel=INFO
```

---

## Environment Variables

See [`.env.example`](.env.example) for all required values. Key ones:

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather token |
| `TELEGRAM_WEBHOOK_URL` | Public HTTPS URL ending in `/bot/webhook` |
| `GOOGLE_API_KEY` | Gemini API key (LLM + embeddings) |
| `YANDEX_GEOCODE_API_KEY` | Yandex Maps Geocoder |
| `YANDEX_ROUTING_API_KEY` | Yandex Routing (commute scoring) |
| `DOMAIN` | Your domain (production only, used by nginx) |

---

## Repository Layout

```
apps/
├── bot/          # aiogram handlers · FSM states · keyboards
├── workers/      # Celery tasks — scrape · enrich · match · digest · kpi
└── shared/       # SQLAlchemy models · scoring · feedback · config
infra/
└── nginx.conf    # reverse proxy template (SSL + webhook routing)
alembic/          # 5 DB migrations (listings → users → matches → feedback)
tests/unit/       # 60+ pytest unit tests
docs/superpowers/ # implementation plans (Plans 1–4)
```

---

## Production Deployment

```bash
ssh admin@your-server
git clone https://github.com/abdullayevf/scout.git /home/admin/scout
cd /home/admin/scout
cp .env.example .env  # fill in production values
./deploy.sh
```

See [`docker-compose.prod.yml`](docker-compose.prod.yml) for production port overrides.

---

## License

MIT
