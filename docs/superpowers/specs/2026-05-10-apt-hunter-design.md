# AI Apartment Hunter — MVP Design Spec

**Status:** approved (2026-05-10)
**Product name:** **Scout**
**Scope:** MVP, Tashkent only, Telegram-only delivery
**Owner / maintainer:** [@golibabdullayev](https://t.me/golibabdullayev)

---

## 1. Problem & Goal

Apartment search in Tashkent is fragmented across OLX and dozens of Telegram channels, listings repeat, stale ones waste effort, and users burn out before securing acceptable housing. Existing platforms optimize for inventory browsing, not for getting a renter into a good unit fast.

**Primary goal.** Reduce **median days from onboarding to a successful rental outcome** for users who complete onboarding and stay engaged.

**Secondary goals.** Cut scrolling time, suppress duplicates and dead listings, surface time-sensitive matches before they're gone, prioritize precision over recall (better to send 3 great picks than 30 mediocre ones).

---

## 2. Scope

**In scope (MVP):**

- Single market: **Tashkent, Uzbekistan**.
- Single source: **olx.uz** (Telegram channels deferred to Phase 2).
- All housing intents: whole apartments for families, whole apartments for solo / couple, room-in-shared-flat (gender-aware), and "looking for a roommate" — selected by `search_type` at onboarding.
- Telegram bot for **both onboarding and delivery**. No web app, no mobile app, no email.
- Russian-canonical text pipeline (Uzbek Latin & Cyrillic auto-translated at ingest); UZS-canonical pricing.
- Daily 09:00 local digest + instant alerts for top-1% matches + Sunday weekly check-in.
- Rules + cosine ranking in the hot path; LLM only at ingest and onboarding.

**Explicitly out of scope (MVP):**

- Telegram channel ingestion (Phase 2).
- Web/mobile UI for end users.
- Autonomous AI agents, voice, landlord calling, contracts, payments.
- Recommendation social feeds, marketplace/chat between users.
- Vision-LLM analysis of listing photos.
- LLM in the per-match hot path.
- Premium tiers, broker tools, relocation flows, roommate matching, multi-city.

---

## 3. Users & Segmentation

Captured at onboarding and used as hard filters + ranking inputs:

| Field | Values |
|---|---|
| `search_type` | `whole_apt_family`, `whole_apt_solo`, `shared_room`, `looking_for_roommate` |
| `gender_pref` | `any`, `male`, `female` (asked only if `search_type ∈ {shared_room, looking_for_roommate}`) |
| `agent_filter` | `owner_only`, `agents_ok` |
| `budget_min`, `budget_max` | UZS |
| `rooms` | any / 1 / 2 / 3+ |
| `areas[]` | multi-select Tashkent tumans (see §3.1) + optional custom area/landmark strings |
| `move_in_window` | `now`, `2_weeks`, `1_month`, `flexible` |
| `commute_origin` | geocoded address (Yandex) |
| `commute_max_minutes`, `commute_mode` | int, `walk` / `car` / `public` |
| `dealbreakers[]` | multi-select (no shared bathroom, must have parking, no first floor, …) |
| `axis_priority{budget,area,commute,rooms,furnishing}` | each ∈ `MUST` (hard filter) or `NICE` (score-only) |
| `tradeoff_hint_text` | optional free text |
| `unacceptable_text` | optional free text |
| `instant_reject_text` | optional free text → keywords extracted to `dealbreaker_keywords[]` |
| `preference_embedding` | 768d Gemini text-embedding-004 |

**Identity:** Telegram `user_id`. No additional auth.

**Mapping `search_type` → OLX categories scraped:**

| `search_type` | Categories |
|---|---|
| `whole_apt_family`, `whole_apt_solo` | Долгосрочная аренда квартир (+ Посуточно if user opts in) |
| `shared_room` | Аренда комнат + Сниму |
| `looking_for_roommate` | Сниму + Аренда комнат |

### 3.1 Tashkent tuman enum

Canonical primary buttons in onboarding `areas[]` step:

`Bektemir`, `Chilanzar`, `Mirobod`, `Mirzo Ulugbek`, `Sergeli`, `Shaykhantakhur`, `Uchtepa`, `Yakkasaray`, `Yashnobod`, `Yunusabad`, `Almazar`, `Yangihayot`

**Plus a `+ Add custom area / landmark` free-text option** — accepts strings like `"Чиланзар-19"`, `"рядом с TUIT"`, `"м. Буюк Ипак Йули"`. Custom areas match against listings via:

1. Substring match on `listing.location_text` (case-insensitive, RU/UZ-Latn/UZ-Cyrl normalized)
2. Yandex geocode of the custom string → radius match against `listing.lat`/`lng` (default 1.5 km)

A listing matches `user.areas` if it matches the listing's tuman OR any of the user's custom area strings.

### 3.2 Bot meta (Telegram)

- **Bot username:** [@scout_apt_bot](https://t.me/scout_apt_bot)
- **Bot description (Telegram bio, ≤512 chars):**
  > AI-помощник по поиску квартир в Ташкенте.
  > Каждый день подбирает лучшие варианты под твои критерии — без дублей и старых объявлений.
  > Built by @golibabdullayev.
- **Bot short description (Telegram about, ≤120 chars):**
  > Умный поиск квартир в Ташкенте. Ежедневная подборка под твои критерии.
- **`/start` welcome screen** (sent first time the user opens the bot, before onboarding):
  > 👋 Привет! Я Scout — помогу найти квартиру в Ташкенте быстрее.
  >
  > Что я делаю:
  > • Каждые 5 минут проверяю новые объявления на OLX
  > • Убираю дубли, старые объявления и подозрительные посты
  > • Раз в день в 09:00 присылаю 8 лучших вариантов под твои критерии
  > • Сразу присылаю горячие топ-варианты (макс. 3/день)
  > • Учусь на твоих 👍 и 👎 — со временем рекомендации становятся точнее
  >
  > Готов начать? Займёт ~2 минуты.
  > [ Начать ▶️ ]
- **`/help` screen** (always available):
  > Команды:
  > /settings — изменить критерии поиска
  > /reonboard — пройти опрос заново
  > /pause — поставить поиск на паузу
  > /resume — возобновить поиск
  > /delete — удалить все мои данные
  > /help — это сообщение
  >
  > Вопросы и предложения: @golibabdullayev
- **Credits in the bot bio + `/help` footer:** `Built by @golibabdullayev`

---

## 4. Onboarding Flow (Telegram Bot)

Hybrid: structured buttons for hard fields, optional free-text for nuance.

**Step 1 — Structured (8–12 taps):**

1. `search_type` (4 buttons)
2. `gender_pref` (3 buttons; only shown if relevant)
3. Budget — preset ranges + custom input fallback
4. Rooms count
5. Areas — multi-select district list
6. Move-in window
7. Commute origin (free-text address → geocoded), commute max minutes, transport mode
8. Dealbreakers — multi-select
9. `agent_filter`
10. Per-axis MUST vs NICE marker

**Step 2 — Free-text wall:**

> ✅ All set! Want to personalize further? It helps me match better. (3 quick questions, ~1 min)
> [ Yes ] [ Skip ]

If **Yes** → ask one at a time, each prefixed `(1/3) (2/3) (3/3)`, each with its own `[Skip]` button:

1. *"Would you rather exceed budget or exceed commute?"*
2. *"What made previous apartments unacceptable?"*
3. *"What's an instant reject?"*

If **Skip** at the wall → no free-text answers stored. `preference_embedding` is built from the structured prefs alone (no degraded ranking, just less nuance).

**Step 3 — Profile build (background):**

Gemini 2.5 Flash extracts:

- `dealbreaker_keywords[]` from the "instant reject" answer (added to existing dealbreakers list)
- `tradeoff_hint_text` and `unacceptable_text` retained as raw text fields for later use
- A serialized text representation of all prefs is sent to Gemini text-embedding-004 → `preference_embedding`

**Preference editing:**

- `/settings` → button menu of editable axes (Budget, Areas, Search type, Gender pref, Commute, Dealbreakers, Notifications). Tap an axis to edit just it.
- `/reonboard` → re-runs the full interview. Old `preference_embedding` is replaced.
- Free-text re-edit deferred to Phase 1.5.

---

## 5. Sources & Ingestion

### 5.1 Scraping

- **Source:** olx.uz only.
- **Categories:** the union of all categories required by any active user's `search_type`.
- **Cadence:** every 5 minutes per active category. Exponential backoff on errors. Polite enough to avoid IP bans; fast enough that "instant alert" feels instant.
- **Stack — two-tier:**
  1. **Default path: `httpx` + `selectolax`** for list pages and detail pages. OLX list/detail pages are largely server-rendered HTML; lightweight HTTP parsing handles them at ~50 ms/page with rotated User-Agents and a small residential proxy pool. ~10× cheaper than full Playwright in CPU + RAM.
  2. **Playwright fallback (only for phone-reveal step):** OLX hides the contact phone behind a "Show phone" click that fires a JS request. A pooled headless Playwright worker handles this single action per listing on first ingest. Result is cached on the listing row — Playwright is never invoked twice for the same listing.
- **Anti-bot escape hatch:** if `httpx`-tier success rate drops below 80 % in a rolling hour (Cloudflare challenges, etc.), the scrape task auto-falls-back to Playwright for that category until the success rate recovers. Alert fires if Playwright path is needed for >24h.
- **Fields collected per listing:** `source`, `source_url`, `title`, `description`, `price_raw`, `currency_raw`, `location_text`, `rooms`, `floor`, `posted_at`, `contact_phone_raw`, `image_urls[]`, `seller_label` (owner / agent if exposed by OLX).

### 5.2 Enrichment (per listing, runs once on ingest)

Pipeline:

1. **Image download.** All images saved to local volume (S3-compatible later). pHash computed per image and stored.
2. **Language detection** (`ru` / `uz-latn` / `uz-cyrl`).
3. **Translation to RU** via Gemini for non-RU listings — original kept verbatim, translated text stored in `description_ru`.
4. **Currency normalization** to UZS using daily CBU rate.
5. **LLM normalization & classification** (Gemini 2.5 Flash, structured output): `search_type_listing`, `gender_constraint_listing`, `is_furnished`, `has_parking`, `floor`, `total_floors`, `is_first_floor`, `bathroom_type`, `agent_listed_bool`, `agent_fee_text` (if present), `summary_one_line`.
6. **Embedding** — `description_ru + summary_one_line + structured fields` → 768d Gemini embedding stored in pgvector.
7. **Risk score** — heuristic, no LLM:
   - +1 if `price_uzs` < (area_median − 2σ)
   - +1 if `phone_hash` seen on > N (config) unrelated listings in trailing 14d
   - +1 per pHash collision with prior listings whose phone differs
   - +1 if "agent" / "посредник" / "комиссия" keywords detected and `agent_listed_bool = false`
   - Score ≥ HARD_THRESHOLD → `suppressed = true` (never sent).
   - Score ≥ SOFT_THRESHOLD → keep, attach warning tags to match reasons.

### 5.3 Deduplication

Runs at the end of enrichment, before fanout:

| Tier | Trigger | Action |
|---|---|---|
| Hard dup | same `phone_hash` OR same `pHash` (exact) | collapse — keep newest, link older to it |
| Likely dup | same normalized address + price within 5 % + same rooms | collapse — keep newest |
| Soft dup | embedding cosine ≥ 0.95 AND price within 5 % | suppress in digest, keep both rows in DB |
| Repost | same `source_url` re-seen ≤ 30 d | keep first, update `last_seen_at`, recompute freshness |

### 5.4 Listing Lifecycle

- **Daily re-fetch** of every active listing URL at 03:00 UTC. 404 / "sold" / removed → `state = dead`.
- **Freshness decay:** `freshness_score = 0.5 ^ (age_days / 14)`, applied at score time.
- **Retention:** dead listings keep body for 60d (so dedup catches reposts), then body + raw phone purged. pHash + phone_hash kept indefinitely.

---

## 6. Ranking & Matching

### 6.1 Hot path (no LLM)

For each freshly enriched listing, fan out to all active (non-paused) users:

```
1. Apply hard filters from user's MUST-marked axes:
   - search_type compatibility (user.search_type ↔ listing.search_type_listing)
   - gender_constraint compatibility
   - agent_filter
   - budget MUST → price_uzs in [budget_min, budget_max]
   - area MUST → listing.area in user.areas
   - commute MUST → Yandex routing(commute_origin → listing.coords, mode) ≤ commute_max_minutes
   - rooms MUST → listing.rooms == user.rooms (or both "any")
   - structured dealbreakers (from multi-select) — mapped to listing structured fields:
       "no shared bathroom"   → listing.bathroom_type != "shared"
       "must have parking"    → listing.has_parking == true
       "no first floor"       → listing.is_first_floor == false
       (full mapping table maintained alongside the dealbreaker enum)
   - dealbreaker_keywords (from free-text "instant reject" extraction) — must NOT appear in description_ru
   - listing.suppressed == false
   - listing not in user.seen_set
   - listing.poster not in user.distrust_set
   If any MUST filter fails → drop, do not score.

2. cosine = vector_cosine(user.preference_embedding, listing.embedding)

3. score =
     w_cosine        * cosine
   + w_budget        * budget_score(listing.price_uzs, user.budget_min, user.budget_max)
   + w_commute       * commute_score(routing_minutes, user.commute_max_minutes)
   + w_freshness     * 0.5 ^ (age_days / 14)
   + w_source_rep    * source_score(listing.poster_phone_hash)
   + w_axis_bonus    * sum(NICE-axis match bonuses)
   - w_risk          * risk_score
   weights are per-axis tunable; see config table below

4. If score >= INSERT_THRESHOLD:
     INSERT INTO matches (user_id, listing_id, score, reasons[], state='pending')

5. If score >= user.top_1pct_threshold:
     IF outside quiet hours AND user.daily_instant_count < 3:
       enqueue instant alert
     ELSE:
       leave pending → next 09:00 digest
```

`top_1pct_threshold` is the rolling 99th-percentile of that user's match scores from the last 14 days, recomputed daily; bootstrap value used during cold start.

### 6.2 Templated reasons

Built from score components. **Show numbers, not math.** Rules:

- `💰 1 400 000 UZS · under your max` (always show price, append `· under your max` if applicable; never percentages)
- `💰 1 800 000 UZS · over budget` (only if budget is NICE, only if other factors strong)
- `🚇 18 min from work` (no comparison phrase — tag implies it passed)
- `🆕 posted 12 min ago` / `🆕 posted 3 h ago` / `🆕 posted yesterday`
- `📍 Yunusabad`
- `👤 owner` / `🏢 agent · fee 50%` (omit fee if not extracted)
- `⚠️ photo possibly reused` (cross-listing pHash collision)
- `⚠️ unusually low price` (price > 2σ below area median)

Each match stores a `reasons: text[]` snapshot — what the user saw, frozen.

### 6.3 Cold start

For each user, until they have ≥ 10 reactions (👍 + 👎 of any kind):

- Replace personalized ranker with a **calibration digest builder**.
- Within hard filters, deliberately stratify the 8 daily picks:
  - 2 from each price quartile of the filtered pool
  - across at least 3 different areas in `user.areas`
  - mix of furnishing levels
- Goal: revealed prefs ≠ stated prefs. Diverse first batch → faster preference learning.
- After ≥ 10 reactions → switch to normal personalized ranker.
- **No instant alerts fire during cold start** (the user's `top_1pct_threshold` is unstable). Calibration users only receive their stratified daily digest.

### 6.4 Feedback math (per-reason routing)

Applied incrementally on each tap, no batch retraining.

| Signal | Update |
|---|---|
| 👍 | `preference_embedding ← normalize(α · pref + (1-α) · listing.embedding)` with small α; bump matched-axis bonus weights; record positive example |
| 📞 Get contact (no 👍) | same as 👍 with a smaller α (intent without affirmation) |
| 👎 💸 too expensive | tighten effective `budget_max` toward this listing's price (running min); bump `w_budget` |
| 👎 📍 bad area | add listing's area to `negative_area_mask[]` (subset within `user.areas`) |
| 👎 🐟 fishy | add `phone_hash` + `poster_id` to `user.distrust_set`; bump global poster reputation penalty |
| 👎 👁 already seen | add `listing_id` to `user.seen_set`; no model update |
| 👎 (generic) | `preference_embedding ← normalize(α · pref - β · listing.embedding)`; record negative example |

Rented (terminal positive): freeze model, mark match `state=rented`, prompt to pause.

---

## 7. Delivery & Notifications

### 7.1 Daily digest

- Sent at **09:00 user-local** (Tashkent UTC+5).
- Up to **8 messages**, one per listing, in score order.
- Header message first: `Доброе утро ☀️ Подобрал 8 вариантов на сегодня`. Suppressed if zero matches.

**Per-listing message format:**

```
[media group: up to 4 images, with ⚠️ "photo possibly reused" caption if flagged]

🏠 2-комн., Yunusabad
💰 1 400 000 UZS · under your max
🚇 18 min from work
🆕 posted 3 h ago
👤 owner

[1-line LLM summary, e.g. "квартира с балконом, без мебели, рядом с метро"]

🔗 olx.uz/...

[ 👍 ] [ 👎 ] [ 📞 Get contact ]
```

After the user taps `👎`, the row is replaced with reason buttons:

```
[ 💸 too expensive ] [ 📍 bad area ] [ 🐟 fishy ] [ 👁 already seen ]
```

`📞 Get contact` reveals the phone number in a follow-up message and marks the match `state=contacted`. This is treated as a stronger intent signal than `👍`.

### 7.2 Instant alerts

- Triggered when a listing scores ≥ user's `top_1pct_threshold`.
- Outside quiet hours (22:00–08:00 Tashkent) and `daily_instant_count < 3` → sent immediately, prefixed `🔥 Свежий топ-вариант`. Format identical to digest.
- During quiet hours OR when daily cap reached → leave in `pending`, will appear in next 09:00 digest at the top.
- `daily_instant_count` resets at 00:00 user-local.

### 7.3 KPI follow-ups (per-listing chase)

- After a user taps `👍` or `📞 Get contact`, schedule a 48 h follow-up:
  > Did you contact "<title>"?
  > [ Yes ] [ No, lost interest ] [ Still planning ]
- On `Yes` → schedule 5-day follow-up:
  > Did you rent it?
  > [ Yes 🎉 ] [ Visited, no ] [ Still deciding ] [ Yes — but a different one ] [ No, still searching ]
- `Yes 🎉` → match `state=rented`, user marked success, soft-stop:
  > Pause searching? [ Yes — pause ] [ Keep going ]

### 7.4 Sunday 18:00 weekly status check

```
Still searching?
[ Yes, keep going ]
[ Found via this bot ]
[ Found elsewhere ]
[ Paused ]
[ Quit ]
```

- `Found via this bot` → paginated picker over recent likes/contacts to attribute the match.
- `Found elsewhere` → mark user success, prompt 1-line free-text "what would have helped?", pause.
- `Paused` → no digests for 14 days, then re-ask.
- `Quit` → `/delete` confirm flow.

---

## 8. Privacy & Retention

### User data

- `/delete` command → confirm button (`⚠️ Delete everything? [Yes, delete] [Cancel]`) → instant wipe of profile + feedback + matches + contacted history.
- Inactive (no message in any direction) > 90 days → auto-purge, single 7-day-prior warning DM.
- "Pause" via Sunday check-in is *not* deletion — data retained, digests stopped.

### Phone numbers (from listings)

- Raw phone stored while listing alive. Shown only after `📞 Get contact` tap.
- Listing dies (404 / sold / age-out) → raw phone purged from the listing row.
- SHA-256 `phone_hash` retained indefinitely for cross-listing dedup + scam scoring + user `distrust_set` lookups.

### Listings

- Body retained 60d after going inactive, then purged.
- pHashes (~16 bytes each) retained indefinitely.

### Logs

- Telegram update logs: 30d retention, then dropped.
- Application/error logs: 30d.

---

## 9. Tech Stack

| Layer | Pick |
|---|---|
| Bot | aiogram (async) |
| API | FastAPI |
| Workers | Celery + Redis (with celery-beat for cron) |
| DB | Postgres + pgvector |
| Scraping | `httpx` + `selectolax` (default); Playwright headless (phone-reveal + anti-bot fallback) |
| Geo | Yandex Maps API (geocoding + routing) |
| LLM | Gemini 2.5 Flash via Google AI Studio (free tier; structured output) |
| Embeddings | Gemini text-embedding-004 (768d) |
| Image storage | Local docker volume (MVP); S3-compatible later |
| pHash | `imagehash` Python lib |
| Hosting | Single Hetzner / DO VPS, docker-compose |
| Telemetry | Postgres event tables + Grafana on Postgres |
| Admin UI | Next.js (Phase 1.5; not at MVP launch) |

### Repo layout

```
apt/
├── docker-compose.yml
├── .env.example
├── apps/
│   ├── api/            # FastAPI: healthchecks, future /settings backend, admin endpoints
│   ├── bot/            # aiogram: onboarding, digest sender, callbacks, follow-ups
│   ├── workers/        # celery tasks
│   └── shared/         # SQLAlchemy models, db, llm client, embedding client, scoring, geo
└── infra/
    └── nginx, certbot configs
```

### Celery beat schedule

| Task | Cadence |
|---|---|
| `scrape:olx:<category>` | every 5 min, per active category |
| `enrich:listings:pending` | every 1 min |
| `match:fanout:listings:enriched` | every 1 min |
| `digest:send` | every 5 min (timezone-aware fire on 09:00 user-local) |
| `alert:instant:scan` | every 1 min |
| `recheck:listings:active` | daily 03:00 UTC |
| `kpi:chase:48h` | hourly |
| `kpi:chase:5d` | hourly |
| `kpi:weekly:status` | Sundays 18:00 Tashkent |
| `purge:user:inactive` | daily 04:00 UTC |
| `purge:listings:dead` | daily 04:30 UTC |
| `recompute:user:top_1pct_threshold` | daily 05:00 UTC |

---

## 10. Data Model (sketch)

```sql
users (
  id, tg_user_id UNIQUE, tg_username,
  search_type, gender_pref, agent_filter,
  budget_min, budget_max, rooms,
  areas TEXT[], move_in_window,
  commute_origin TEXT, commute_origin_lat, commute_origin_lng,
  commute_max_minutes, commute_mode,
  dealbreakers TEXT[], dealbreaker_keywords TEXT[],
  axis_priority JSONB,
  tradeoff_hint_text, unacceptable_text, instant_reject_text,
  preference_embedding vector(768),
  negative_area_mask TEXT[],
  distrust_set TEXT[],          -- phone_hash + poster_id values
  seen_set BIGINT[],            -- listing ids
  top_1pct_threshold FLOAT,
  paused_until TIMESTAMPTZ,
  state TEXT,                   -- active | paused | success | deleted
  success_at TIMESTAMPTZ,
  onboarded_at, last_active_at, created_at, updated_at
);

listings (
  id, source, source_url UNIQUE, source_listing_id,
  title, description_raw, description_ru,
  language_detected, summary_one_line,
  price_raw, currency_raw, price_uzs,
  rooms, floor, total_floors, is_first_floor, bathroom_type,
  is_furnished, has_parking,
  search_type_listing, gender_constraint_listing,
  agent_listed_bool, agent_fee_text,
  area, location_text, lat, lng,
  contact_phone_raw, phone_hash,
  poster_id,
  image_urls TEXT[], image_phashes TEXT[],
  embedding vector(768),
  risk_score INT, suppressed BOOL,
  state TEXT,                   -- pending_enrich | active | dead
  posted_at, last_seen_at, dead_at, body_purged_at,
  created_at, updated_at
);

matches (
  id, user_id, listing_id,
  score FLOAT, reasons TEXT[],
  state TEXT,                   -- pending | sent | liked | disliked | contacted | rented | dead
  liked_at, disliked_at, dislike_reason TEXT,
  contacted_at, rented_at,
  chase_48h_due_at, chase_48h_done_at,
  chase_5d_due_at, chase_5d_done_at,
  delivered_via TEXT,           -- digest | instant
  created_at, updated_at,
  UNIQUE (user_id, listing_id)
);

events (                          -- append-only telemetry
  id, ts, kind, user_id, listing_id, match_id, payload JSONB
);
```

---

## 11. KPIs

**Primary:** median **`days_from_onboarding_to_success`**, where success = match `state = rented` OR Sunday status `Found via this bot` / `Found elsewhere`.

**Secondary:**

1. 👍 rate per digest message
2. `📞 Get contact` rate per digest message
3. 👍 → confirmed-contact conversion (from 48h chase)
4. confirmed-contact → rented conversion (from 5-day chase)
5. Daily-active rate (any button tap on the day's digest)
6. Mute / block / `/delete` rate

**MVP launch validation gate (before scaling beyond first 10 users):**

- ≥ 50 % of cohort reaches success state
- Median `days_to_success` ≤ 21 days
- Mute / block rate < 20 %
- ≥ 1 listing per user per week is rated 👍
- Qualitative: ≥ half the cohort would recommend the bot

---

## 12. Phasing

**Phase 1 — MVP (this spec).** OLX-only, Telegram bot, 5–10 manually onboarded users. Goal: validate ranking utility and KPI funnel. Build ~4–6 weeks, operate ~4 weeks.

**Phase 1.5 — refinements.** Scam-detection tuning, optional LLM re-rank of top-K via free OpenRouter model, Next.js admin (listing inspector, user inspector, KPI dashboards), more OLX categories if needed, free-text preference editing.

**Phase 2 — Telegram channel ingestion.** MTProto user-account scraper for ingest; existing bot continues delivery. Adds the largest source of unique inventory in Tashkent. Defer until Phase 1 validates utility.

**Phase 3 — out of MVP scope, validate first.** Premium alerts, broker tools, relocation, roommate matching, paid search automation, multi-city.

---

## 13. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| OLX scraping breakage / IP ban | 5-min cadence (not faster), Playwright + UA/cookie rotation, exponential backoff, per-category retry queues, alerts on extended failure |
| Poor recommendation quality | Conservative hard filters, calibration cold-start, per-reason feedback routing, precision-over-recall stance (8 picks/day cap) |
| Stale inventory | Daily re-fetch + freshness decay + repost detection |
| Scam exposure | Heuristic risk score with hard auto-suppress + soft warning tags + cross-listing pHash collision detection |
| Free LLM rate limits | Only used at ingest (one-shot per listing) and onboarding (one-shot per user); retry with backoff; non-critical reason-rewrite path is excluded |
| User burnout / bot mute | 8/day digest cap, 3/day instant cap, quiet hours, per-listing chase only on user-initiated signals (👍 / contact) |
| Yandex Maps cost / quota | Cache geocoding results aggressively (one geocode per unique address); commute-time only computed for listings that pass other filters |
| Privacy / phone-data exposure | Raw phones purged when listing dies; `/delete` is instant + complete; `phone_hash` is the only long-term phone artifact |

---

## 14. Open Items (non-blocking; carried into implementation)

- Initial values for ranking weights `w_cosine, w_budget, w_commute, w_freshness, w_source_rep, w_axis_bonus, w_risk` — start with hand-tuned defaults; tune after first cohort feedback.
- Initial values for `INSERT_THRESHOLD`, `HARD_THRESHOLD`, `SOFT_THRESHOLD`.
- Bootstrap value for `top_1pct_threshold` before per-user history accumulates.
- Embedding update step sizes (α for likes, α/β for dislikes).
- Residential proxy provider for `httpx` tier (e.g. existing lobstr.io infra vs. third-party).

---

## 15. User Flow Summary

1. User starts bot → onboarding (structured + optional free-text wall).
2. Profile + preference embedding stored.
3. Ingestion runs continuously; new listings are enriched + deduped + scored against all active users.
4. Calibration digest first ~10 reactions; personalized digest thereafter.
5. Daily 09:00 digest (8 messages) + instant alerts (≤3/day) + Sunday weekly check.
6. Each `👍` or `📞 Get contact` triggers 48h then 5d follow-up chase.
7. `Rented` outcome → success, pause prompt.
8. Inactive >90d → auto-purge (with prior warning).
