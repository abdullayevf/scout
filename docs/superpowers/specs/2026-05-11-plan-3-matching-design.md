# Scout — Plan 3: Matching, Digest & Instant Alerts Design Spec

**Status:** approved (2026-05-11)
**Scope:** `matches` table, push-from-enrich match fanout, hard filters + scoring formula, templated reasons, daily 09:00 Tashkent digest, instant alerts for top-1% matches, cold-start stratified picks, top-1% threshold recompute, bot digest sender, stub callback handlers.
**Follows:** Plan 2 (bot onboarding complete; users have `state='active'`, `preference_embedding`)
**Precedes:** Plan 4 (feedback ML, KPI chase, weekly check-in)

---

## 1. Goal & Boundary

**Goal.** Every freshly enriched listing is scored against every active user; surviving matches land in a `matches` table; users receive a daily 09:00 Tashkent digest of up to 8 picks and instant alerts for top-1% matches (≤3/day, quiet-hour gated). New users get diversified picks until they've accumulated reactions.

**Verification gate.** Real maintainer accounts receive properly formatted digest messages with working buttons, and instant alerts fire within seconds of ingest for high-scoring matches.

**Plan 3 ↔ Plan 4 boundary.** Plan 3 *sends* the messages and *logs* button taps as `events`. Plan 4 owns `matches.state` transitions (liked/disliked/contacted/rented), embedding updates, `negative_area_mask`/`distrust_set` writes, budget tightening, KPI chase, and weekly check-in. The contact-phone reveal is the one exception: Plan 3 owns it, because without it the digest is unusable for verification.

---

## 2. Architecture & End-to-End Flow

A single new module surface — **`apps/shared/matching/`** — holds the scoring math, reason templating, and cold-start stratifier. No new docker-compose service. Workers gain four Celery tasks; the bot gains three stub callback handlers and a digest sender helper.

```
[enrich_listing finishes]
        │  row.state = ACTIVE  ──►  dispatch match.fanout.listing(listing_id)
        ▼
[match.fanout.listing]                              (Celery, per listing)
   1. SQL filter: state='active', search_type compat, budget MUST,
      agent_filter, NOT seen, NOT distrust   → ~10–100 candidates
   2. Python filter (per candidate): area, commute (Yandex routing,
      cached), rooms, dealbreakers, keywords, negative_area_mask
   3. Score + reasons → INSERT matches if ≥ INSERT_THRESHOLD
   4. If score ≥ user.top_1pct_threshold AND not cold-start
        → enqueue match.alert.instant(match_id)

[match.alert.instant]                               (Celery, per match)
   - Quiet hours gate (22:00–08:00 Tashkent, hardcoded)
   - Daily cap gate (≤3 instants delivered since 00:00 user-local)
   - send_match_message(..., prefix="🔥 Свежий топ-вариант")
   - matches.state='sent', delivered_via='instant'

[digest.send.daily]                                 (beat: 04:00 UTC = 09:00 Tashkent)
   Fans out one digest.send.user task per active user.

[digest.send.user]                                  (Celery, per user)
   - SELECT pending matches for user
   - If is_cold_start(user): stratified_pick(k=8)
     Else:                   top-8 by score
   - Send header + per-listing messages with inline keyboard
   - matches.state='sent', delivered_via='digest'

[match.threshold.recompute]                         (beat: 05:00 UTC)
   - Per user, recompute top_1pct_threshold from 14d match-score history
   - Bootstrap from global p99 or constant when history is thin

[match.cleanup.dead]                                (beat: 04:45 UTC)
   - UPDATE matches SET state='dead' WHERE listing went dead
```

Cold-start during Plan 3's validation window: `is_cold_start()` counts `matches.state ∈ {liked, disliked, contacted}`. Because Plan 3 doesn't transition those states, every user is permanently in cold-start — digest path exercises stratification, instant-alert path requires a manual DB nudge for verification. Plan 4 will make this exit organically.

---

## 3. File Map

| Path | Action | Purpose |
|---|---|---|
| `apps/shared/matching/__init__.py` | create | re-exports |
| `apps/shared/matching/score.py` | create | hard filters + scoring formula |
| `apps/shared/matching/reasons.py` | create | templated reason builders |
| `apps/shared/matching/coldstart.py` | create | `is_cold_start()`, `stratified_pick()` |
| `apps/shared/matching/config.py` | create | weights, thresholds, quiet hours (env-overridable) |
| `apps/shared/telegram_send.py` | create | sync wrapper around aiogram Bot for workers |
| `apps/shared/models.py` | modify | add `Match` model |
| `apps/shared/enums.py` | modify | add `MatchState`, `DeliveredVia` |
| `apps/shared/config.py` | modify | add matching env overrides (optional) |
| `apps/workers/tasks/match.py` | create | fanout, instant alert, threshold recompute, cleanup |
| `apps/workers/tasks/digest.py` | create | daily digest fanout + per-user sender |
| `apps/workers/tasks/enrich.py` | modify | dispatch `match_fanout_listing.delay(id)` on success |
| `apps/workers/celery_app.py` | modify | register new tasks + 3 new beat entries |
| `apps/bot/handlers/match_callbacks.py` | create | stub 👍 / 👎 / 📞 handlers |
| `apps/bot/handlers/__init__.py` | modify | register match_callbacks router |
| `apps/bot/keyboards.py` | modify | `match_actions_kb`, `dislike_reasons_kb` |
| `apps/bot/messages.py` | modify | reason emoji + tuman RU strings |
| `apps/bot/main.py` | modify | wire router |
| `alembic/versions/<hash>_add_matches.py` | create | migration |
| `tests/unit/test_scoring.py` | create | hard filter truth table + score components |
| `tests/unit/test_reasons.py` | create | reason string formatting |
| `tests/unit/test_coldstart.py` | create | gate + stratifier |
| `tests/unit/test_match_fanout.py` | create | testcontainers Postgres + pgvector |
| `tests/unit/test_digest_pick.py` | create | digest picker (cold-start + normal) |
| `tests/unit/test_threshold_recompute.py` | create | personal p99, global p99, bootstrap |

---

## 4. Data Model

### 4.1 `matches` table

```sql
matches (
  id                  BIGSERIAL PRIMARY KEY,
  user_id             BIGINT  NOT NULL,
  listing_id          BIGINT  NOT NULL,
  score               FLOAT   NOT NULL,
  reasons             TEXT[]  NOT NULL DEFAULT '{}',
  state               VARCHAR(16) NOT NULL DEFAULT 'pending',
                                       -- pending | sent | liked | disliked
                                       -- | contacted | rented | dead
  delivered_via       VARCHAR(8),      -- 'digest' | 'instant' | NULL
  dislike_reason      VARCHAR(32),     -- reserved for Plan 4
  liked_at            TIMESTAMPTZ,
  disliked_at         TIMESTAMPTZ,
  contacted_at        TIMESTAMPTZ,
  rented_at           TIMESTAMPTZ,
  chase_48h_due_at    TIMESTAMPTZ,     -- reserved for Plan 4
  chase_48h_done_at   TIMESTAMPTZ,
  chase_5d_due_at     TIMESTAMPTZ,
  chase_5d_done_at    TIMESTAMPTZ,
  created_at          TIMESTAMPTZ DEFAULT now(),
  updated_at          TIMESTAMPTZ DEFAULT now(),
  UNIQUE (user_id, listing_id)
)
```

**Indexes:**

| Index | Purpose |
|---|---|
| `(user_id, state, score DESC)` | Digest picker: top-N pending per user |
| `(user_id, delivered_via, created_at)` | Instant cap counter |
| `(state, score)` partial `WHERE state='pending'` | Instant alert scanner (rare path, kept for cheap reads) |
| `(listing_id)` | Listing-death cleanup |

No foreign keys — matches Plan 2's convention; avoids cross-plan cascade complexity. The chase columns and `dislike_reason` are reserved now even though Plan 4 owns the writes; adding columns later forces an extra migration and re-deploy at a worse time. Cost is ~40 bytes of NULLs per row.

### 4.2 Enum additions (`apps/shared/enums.py`)

```python
class MatchState(StrEnum):
    PENDING   = "pending"
    SENT      = "sent"
    LIKED     = "liked"        # Plan 4 writes
    DISLIKED  = "disliked"     # Plan 4 writes
    CONTACTED = "contacted"    # Plan 4 writes
    RENTED    = "rented"       # Plan 4 writes
    DEAD      = "dead"

class DeliveredVia(StrEnum):
    DIGEST  = "digest"
    INSTANT = "instant"
```

### 4.3 `apps/shared/matching/config.py`

```python
W_COSINE       = 0.40
W_BUDGET       = 0.20
W_COMMUTE      = 0.15
W_FRESHNESS    = 0.10
W_SOURCE_REP   = 0.05
W_AXIS_BONUS   = 0.07
W_RISK         = 0.10        # subtracted

INSERT_THRESHOLD            = 0.20
COLD_START_REACTIONS        = 10
INSTANT_DAILY_CAP           = 3
QUIET_HOURS_START           = 22     # Tashkent local
QUIET_HOURS_END             = 8
GLOBAL_TOP1PCT_BOOTSTRAP    = 0.75
THRESHOLD_MIN_PERSONAL      = 50     # min personal scores before per-user p99
THRESHOLD_MIN_GLOBAL        = 200    # min global scores before bootstrap kicks in
```

All values are module constants; env vars `MATCHING_W_COSINE`, etc. override at import time if set.

---

## 5. Scoring

### 5.1 Hard filters

Any failure → drop the (user, listing) pair, no score computed, no row inserted.

1. `user.state == 'active'`
2. `search_type` compatibility (truth table mapping `user.search_type` → acceptable `listing.search_type_listing` values)
3. `gender_constraint` compatibility (only meaningful when `user.search_type ∈ {shared_room, looking_for_roommate}`)
4. If `user.agent_filter == 'owner_only'` → `listing.poster_role != 'agent'`
5. Budget MUST → `budget_min ≤ listing.price_uzs ≤ budget_max`
6. Area MUST → listing's tuman in `user.areas`, OR custom-area substring match on `listing.location_text`
7. Commute MUST → Yandex routing minutes ≤ `user.commute_max_minutes`
8. Rooms MUST → `listing.rooms == user.rooms` (NULL on user side = "any")
9. Structured dealbreakers per master spec §6.1 mapping table
10. `dealbreaker_keywords` not present in `description_ru`
11. `listing.suppressed == false` AND `listing.canonical_listing_id IS NULL`
12. `listing.id NOT IN user.seen_set`
13. `listing.phone_hash NOT IN user.distrust_set`
14. Listing's area not in `user.negative_area_mask`

Filters 1, 2, 4, 5, 11, 12, 13 run as SQL `WHERE` clauses in `sql_filter_candidates(s, listing)`. Filters 3, 6, 7, 8, 9, 10, 14 run in Python because they need per-listing computation (geocode, Yandex routing) or array-membership the SQL filter can't pre-compute cheaply.

### 5.2 Score components

Each component ∈ [0, 1] before weighting; `risk_penalty` is capped at 3 then divided by 3.

```
cosine        = pgvector cosine(user.preference_embedding, listing.embedding)
                normalized to [0, 1] via (1 + raw) / 2

budget_score  = 1.0 if price ≤ budget_max
                linear decay to 0 as price → 1.5 × budget_max
                (used only when budget is NICE; MUST already gated)

commute_score = 1.0 if minutes ≤ commute_max
                linear decay to 0 as minutes → 1.5 × commute_max
                If commute origin or listing coords absent → component dropped,
                weight redistributed proportionally to remaining components.

freshness     = 0.5 ^ (age_days / 14)    where age = now() - listing.posted_at

source_rep    = 1.0 if listing.poster_role == 'owner'
                0.7  if 'agent' (only reachable when user.agent_filter='agents_ok')
                0.5  if 'unknown'
                minus 0.3 if phone_hash appears in many distrust_sets
                clamped to [0, 1]

axis_bonus    = (#NICE-axes satisfied) / (#NICE-axes total)
                (skipped axes don't count toward total)

risk_penalty  = listing.risk_score   (0..3, capped)
```

### 5.3 Final score

```
score = W_COSINE     * cosine
      + W_BUDGET     * budget_score        (only if budget axis = NICE)
      + W_COMMUTE    * commute_score       (only if commute_score is defined)
      + W_FRESHNESS  * freshness
      + W_SOURCE_REP * source_rep
      + W_AXIS_BONUS * axis_bonus
      - W_RISK       * (risk_penalty / 3)
```

Range roughly [−0.10, ~1.0]. `INSERT_THRESHOLD = 0.20` drops anything below ~20% confidence before it lands in `matches`.

### 5.4 Cold-start digest stratifier

`coldstart.stratified_pick(pending_matches, user, k=8)`:

1. Bucket pending matches into 4 price quartiles (computed from the candidate pool itself, not the user's budget).
2. Round-robin pick from buckets: 2 per quartile baseline.
3. **Areas constraint:** after the initial pick, if fewer than 3 distinct areas are represented and the user has ≥3 areas selected, swap the lowest-scored pick in over-represented areas for a higher-scored pick from under-represented areas.
4. **Furnishing mix:** if all 8 picks share the same `is_furnished`, swap the lowest-scored pick for the highest-scored pick of the opposite value.
5. Return up to `k` listings, score-ordered within stratification constraints.

If `len(pending) < 8`, send what we have (no padding).

### 5.5 Top-1% threshold recompute

Daily 05:00 UTC. Per-user:

```python
user_scores = SELECT score FROM matches
              WHERE user_id = user.id
                AND created_at > now() - 14d

if len(user_scores) >= THRESHOLD_MIN_PERSONAL:        # 50
    user.top_1pct_threshold = percentile(user_scores, 99)
else:
    global_scores = SELECT score FROM matches
                    WHERE created_at > now() - 14d
    if len(global_scores) >= THRESHOLD_MIN_GLOBAL:    # 200
        user.top_1pct_threshold = percentile(global_scores, 99)
    else:
        user.top_1pct_threshold = GLOBAL_TOP1PCT_BOOTSTRAP   # 0.75
```

`GLOBAL_TOP1PCT_BOOTSTRAP = 0.75` is conservative; combined with cold-start gating, very few instant alerts fire until the system has real data.

---

## 6. Workers

### 6.1 `match.fanout.listing(listing_id)` — push from enrich

Dispatched from the `enrich_listing` wrapper **after `_enrich_one` returns successfully**, not from inside `_enrich_one`. `_enrich_one` runs inside `session_scope()`; dispatching `.delay()` before that context exits would race the commit and the fanout worker could see `state=PENDING_ENRICH`.

```python
@app.task(name="enrich.listing", bind=True, max_retries=3, default_retry_delay=120)
def enrich_listing(self, listing_id: int) -> dict:
    result = _enrich_one(listing_id)
    if result.get("ok"):
        match_fanout_listing.delay(listing_id)
    return result
```

Task body:

```python
@app.task(name="match.fanout.listing", bind=True, max_retries=2, default_retry_delay=60)
def match_fanout_listing(self, listing_id: int) -> dict:
    with session_scope() as s:
        listing = s.get(Listing, listing_id)
        if not listing or listing.state != ListingState.ACTIVE or listing.suppressed:
            return {"ok": False, "reason": "not eligible"}
        if listing.canonical_listing_id is not None:
            return {"ok": False, "reason": "dedup'd to canonical"}

        candidates = sql_filter_candidates(s, listing)

        inserted = 0
        for user in candidates:
            if not python_filter_pass(user, listing):
                continue

            score, reasons, components = score_listing_for_user(user, listing)
            if score < INSERT_THRESHOLD:
                continue

            m = Match(
                user_id=user.id, listing_id=listing.id,
                score=score, reasons=reasons, state=MatchState.PENDING,
            )
            s.add(m)
            s.flush()
            inserted += 1

            if not is_cold_start(s, user) and score >= (user.top_1pct_threshold or 999):
                match_alert_instant.delay(m.id)

        return {"ok": True, "candidates": len(candidates), "inserted": inserted}
```

`sql_filter_candidates` shape:

```sql
SELECT * FROM users WHERE
    state = 'active'
    AND search_type IN (:compat_types)
    AND (
      (axis_priority->>'budget' = 'NICE')
      OR (:listing_price BETWEEN COALESCE(budget_min,0) AND COALESCE(budget_max, 1e18))
    )
    AND (agent_filter = 'agents_ok' OR :listing_role != 'agent')
    AND NOT (:listing_id = ANY(seen_set))
    AND (:listing_phone_hash IS NULL OR NOT (:listing_phone_hash = ANY(distrust_set)))
```

Yandex routing is the expensive call. `python_filter_pass` only invokes routing when commute is MUST AND the listing has lat/lng. Per-`(user, listing.lat, listing.lng, mode)` routing results cached in `GeocodeCache` (Plan 1's table — extend with a routing variant, or add a sibling `RoutingCache` table; either works).

### 6.2 `match.alert.instant(match_id)`

Triggered immediately from fanout, not by a beat scanner.

```python
@app.task(name="match.alert.instant", bind=True, max_retries=2)
def match_alert_instant(self, match_id: int) -> dict:
    with session_scope() as s:
        m = s.get(Match, match_id)
        if not m or m.state != MatchState.PENDING:
            return {"ok": False, "reason": "state changed"}
        user = s.get(User, m.user_id)

        now_tashkent = datetime.now(ZoneInfo("Asia/Tashkent"))
        if now_tashkent.hour >= QUIET_HOURS_START or now_tashkent.hour < QUIET_HOURS_END:
            return {"ok": False, "reason": "quiet hours"}

        today_start = now_tashkent.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
        delivered_today = s.execute(
            select(func.count()).select_from(Match)
            .where(Match.user_id == user.id,
                   Match.delivered_via == DeliveredVia.INSTANT,
                   Match.created_at >= today_start)
        ).scalar()
        if delivered_today >= INSTANT_DAILY_CAP:
            return {"ok": False, "reason": "cap reached"}

        listing = s.get(Listing, m.listing_id)
        send_match_message(user, listing, m, prefix="🔥 Свежий топ-вариант")
        m.state = MatchState.SENT
        m.delivered_via = DeliveredVia.INSTANT
        s.add(Event(kind='match_sent_instant', user_id=user.id,
                    listing_id=listing.id, match_id=m.id))
        return {"ok": True}
```

### 6.3 `digest.send.daily` — beat at 04:00 UTC

```python
@app.task(name="digest.send.daily")
def digest_send_daily() -> dict:
    with session_scope() as s:
        ids = s.execute(
            select(User.id).where(User.state == UserState.ACTIVE)
        ).scalars().all()
    for uid in ids:
        digest_send_for_user.delay(uid)
    return {"users": len(ids)}


@app.task(name="digest.send.user", bind=True, max_retries=2)
def digest_send_for_user(self, user_id: int) -> dict:
    with session_scope() as s:
        user = s.get(User, user_id)
        if user.state != UserState.ACTIVE:
            return {"ok": False}

        # Defensive: filter out matches whose listing went dead overnight.
        pending = s.execute(
            select(Match).join(Listing, Listing.id == Match.listing_id)
            .where(Match.user_id == user_id,
                   Match.state == MatchState.PENDING,
                   Listing.state == ListingState.ACTIVE)
            .order_by(Match.score.desc()).limit(200)
        ).scalars().all()

        if not pending:
            return {"ok": True, "matches": 0}

        picks = (
            stratified_pick(pending, user, k=8)
            if is_cold_start(s, user)
            else pending[:8]
        )

        send_digest_header(user, count=len(picks))
        for m in picks:
            listing = s.get(Listing, m.listing_id)
            send_match_message(user, listing, m)
            m.state = MatchState.SENT
            m.delivered_via = DeliveredVia.DIGEST
            s.add(Event(kind='match_sent_digest', user_id=user.id,
                        listing_id=listing.id, match_id=m.id))
        return {"ok": True, "matches": len(picks)}
```

Splitting fanout from per-user send keeps a single slow user from delaying the rest and gives natural retry granularity. If `len(picks) == 0`, no header is sent (per master spec §7.1).

### 6.4 `match.threshold.recompute` — beat at 05:00 UTC

Implements §5.5. One UPDATE per active user; ~5 ms each. Single task, no per-user Celery fanout.

### 6.5 `match.cleanup.dead` — beat at 04:45 UTC

```sql
UPDATE matches SET state='dead', updated_at=now()
WHERE state='pending'
  AND listing_id IN (SELECT id FROM listings WHERE state='dead');
```

Plan 1's `purge:listings:dead` runs at 04:30 UTC; cleanup runs at 04:45 UTC; digest at 04:00 UTC (the next day). For first-day safety the digest task also joins on `Listing.state='active'` (§6.3 above).

### 6.6 Updated Celery beat schedule (additions only)

```python
"digest-send-daily":        {"task": "digest.send.daily",
                             "schedule": crontab(hour=4, minute=0)},  # 09:00 Tashkent
"match-cleanup-dead":       {"task": "match.cleanup.dead",
                             "schedule": crontab(hour=4, minute=45)},
"match-threshold-recompute":{"task": "match.threshold.recompute",
                             "schedule": crontab(hour=5, minute=0)},
```

No `alert.instant.scan` beat — push from fanout means alerts fire end-to-end without polling.

---

## 7. Telegram Send Wrapper

`apps/shared/telegram_send.py` exposes sync functions called from Celery workers:

```python
def send_match_message(user: User, listing: Listing, match: Match, prefix: str = "") -> None:
    asyncio.run(_async_send_match_message(user, listing, match, prefix))

def send_digest_header(user: User, count: int) -> None:
    asyncio.run(_async_send_digest_header(user, count))


async def _async_send_match_message(user, listing, match, prefix):
    bot = Bot(token=settings.telegram_bot_token)
    try:
        text = format_match_text(listing, match.reasons, prefix=prefix)
        kb = match_actions_kb(match.id)
        if listing.image_urls:
            await bot.send_media_group(
                chat_id=user.tg_user_id,
                media=[InputMediaPhoto(media=url) for url in listing.image_urls[:4]],
            )
        await bot.send_message(chat_id=user.tg_user_id, text=text, reply_markup=kb)
    finally:
        await bot.session.close()
```

Each Celery task creates and tears down its own `Bot` instance. For 5–10 users × 8 messages/day the overhead is irrelevant; if we ever fan out to thousands, we add a pooled bot.

### 7.1 Message text template

```
🏠 {rooms_str(listing.rooms)}, {tuman_ru(listing.area)}
{chr(10).join(match.reasons)}

{listing.summary_one_line or ''}

🔗 {listing.source_url}
```

Helpers: `rooms_str(2) == "2-комн."`, `rooms_str(None) == "квартира"`, `tuman_ru` maps enum value to display string.

For digests, a header is sent first: `Доброе утро ☀️ Подобрал {N} вариантов на сегодня`. Instants get no header; each individual message is prefixed with `🔥 Свежий топ-вариант`.

---

## 8. Templated Reasons

`apps/shared/matching/reasons.py::build_reasons(user, listing, components) → list[str]`. Pure function, no LLM, no math shown to user.

Output order, per master spec §6.2:

1. **Price** — always present. `💰 1 400 000 UZS · в твоём бюджете` if `price ≤ budget_max`; otherwise `💰 1 800 000 UZS · выше бюджета`.
2. **Commute** — only when user has origin AND listing has coords AND routing succeeded. `🚇 18 мин до работы`.
3. **Freshness** — `🆕 12 мин назад` / `🆕 3 ч назад` / `🆕 вчера` / `🆕 2 дн назад`.
4. **Area** — `📍 Yunusabad` (from `tuman_ru`).
5. **Poster role** — `👤 хозяин` if owner; `🏢 агент` or `🏢 агент · комиссия {fee_text}` if agent and fee was extracted.
6. **Risk warnings** (only soft warnings reach here; hard suppressions never get scored):
   - `⚠️ возможно повторное фото` if `risk_flags['phash_collision']`
   - `⚠️ необычно низкая цена` if `risk_flags['price_outlier']`

The full reasons array is **frozen** into `matches.reasons` at fanout time — the user sees what the listing looked like then, not now.

---

## 9. Bot Integration

### 9.1 Keyboards (`apps/bot/keyboards.py`)

```python
def match_actions_kb(match_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="👍", callback_data=f"like:{match_id}"),
        InlineKeyboardButton(text="👎", callback_data=f"dislike:{match_id}"),
        InlineKeyboardButton(text="📞 Контакт", callback_data=f"contact:{match_id}"),
    ]])

def dislike_reasons_kb(match_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💸 дорого",         callback_data=f"dislike_reason:expensive:{match_id}"),
        InlineKeyboardButton(text="📍 район",          callback_data=f"dislike_reason:area:{match_id}"),
    ], [
        InlineKeyboardButton(text="🐟 подозрительно",  callback_data=f"dislike_reason:fishy:{match_id}"),
        InlineKeyboardButton(text="👁 видел",          callback_data=f"dislike_reason:seen:{match_id}"),
    ]])
```

### 9.2 Stub callback handlers (`apps/bot/handlers/match_callbacks.py`)

```python
@router.callback_query(F.data.startswith("like:"))
async def on_like(cb: CallbackQuery, session: AsyncSession):
    match_id = int(cb.data.split(":", 1)[1])
    await session.execute(insert(Event).values(
        kind='match_btn_like', user_id=cb.from_user.id, match_id=match_id,
    ))
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.edit_text(cb.message.text + "\n\n✅ Запомнил.")
    await cb.answer()

@router.callback_query(F.data.startswith("dislike:"))
async def on_dislike_open(cb: CallbackQuery, session: AsyncSession):
    match_id = int(cb.data.split(":", 1)[1])
    await session.execute(insert(Event).values(
        kind='match_btn_dislike_open', user_id=cb.from_user.id, match_id=match_id,
    ))
    await cb.message.edit_reply_markup(reply_markup=dislike_reasons_kb(match_id))
    await cb.answer()

@router.callback_query(F.data.startswith("dislike_reason:"))
async def on_dislike_reason(cb: CallbackQuery, session: AsyncSession):
    _, reason, mid = cb.data.split(":")
    await session.execute(insert(Event).values(
        kind='match_btn_dislike_reason', user_id=cb.from_user.id,
        match_id=int(mid), payload={"reason": reason},
    ))
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.edit_text(cb.message.text + "\n\n👌")
    await cb.answer()

@router.callback_query(F.data.startswith("contact:"))
async def on_contact(cb: CallbackQuery, session: AsyncSession):
    match_id = int(cb.data.split(":", 1)[1])
    listing = await get_listing_for_match(session, match_id)
    await session.execute(insert(Event).values(
        kind='match_btn_contact', user_id=cb.from_user.id, match_id=match_id,
    ))
    phone = listing.contact_phone_raw or "—"
    await cb.message.answer(f"📞 {phone}\n\n🔗 {listing.source_url}")
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.answer()
```

**Boundary note.** Plan 4 will normally own `matches.state = 'contacted'`. The *phone reveal* is in Plan 3 because the digest is unusable for verification without it. Everything else stays in events-only mode until Plan 4 takes over.

---

## 10. Testing

### 10.1 Unit tests (no live Telegram)

- **`test_scoring.py`** — each of 14 hard filters tested individually; `score_listing_for_user` deterministic for fixed inputs; weights sum check; INSERT_THRESHOLD boundary test.
- **`test_reasons.py`** — output strings for each reason case; price-in-budget vs over-budget formatting; agent fee suffix optional; risk warning flags.
- **`test_coldstart.py`** — `is_cold_start()` returns True when `< 10` reactions; `stratified_pick` produces quartile-balanced selection from synthetic pool; areas constraint enforced when feasible; small pool short-circuits.
- **`test_match_fanout.py`** — testcontainers Postgres + pgvector. Insert one listing + 3 users; call `match_fanout_listing`; verify expected `matches` rows. Cover: budget-MUST drops user, area-MUST drops user, suppressed listing drops all, score-below-INSERT drops match, dedup'd listing drops all.
- **`test_digest_pick.py`** — cold-start path runs stratifier; non-cold-start path returns top 8 by score; empty pending returns no messages; dead listings filtered out.
- **`test_threshold_recompute.py`** — `< 50` personal scores → global p99 or bootstrap; `≥ 50` → personal p99; empty case → bootstrap.

### 10.2 Manual verification (the validation gate)

1. **Live fanout** — maintainer's `User` row is active; enrich one listing; confirm a `matches` row appears with a reasonable score and templated reasons.
2. **Live digest** — manually trigger `digest_send_for_user.delay(maintainer_id)`. Maintainer's Telegram receives 1–8 properly formatted messages with working buttons. Verify each button writes the expected `event` row and edits the message in place.
3. **Live instant alert** — to bypass cold-start for testing, do **one** of:
   - set env var `MATCHING_COLD_START_REACTIONS=1` and force-flip one of maintainer's `matches.state` from `pending` to `liked`, OR
   - directly insert 10 dummy `Match` rows for the maintainer with `state='liked'`.

   Then set `maintainer.top_1pct_threshold = 0` and enrich a new high-scoring listing. Confirm `🔥` alert arrives within seconds, outside quiet hours.
4. **Cap behavior** — repeat step 3 four times; the fourth alert is suppressed, the match stays `state='pending'`, and it appears in the next digest.
5. **Quiet hours** — trigger an instant alert at 23:00 Tashkent → not sent; match stays pending.

---

## 11. Out of Scope (Plan 4)

- `matches.state` transitions to `liked` / `disliked` / `contacted` / `rented` from button taps
- Embedding updates from 👍 / 👎 / 📞
- `negative_area_mask`, `distrust_set`, budget tightening from 👎 reasons
- 48-hour and 5-day KPI chase follow-ups
- Sunday weekly status check-in
- Reaction-conditioned weighting of personal scores in threshold recompute
- `Уведомления` settings UI (still a stub from Plan 2)

---

## 12. Open Knobs Carried into Implementation

- Weights `W_*` — defaults documented in §4.3; tune after first cohort feedback
- `INSERT_THRESHOLD = 0.20` — first cut; will likely move once we see real scores
- `GLOBAL_TOP1PCT_BOOTSTRAP = 0.75` — conservative; cold-start gating means this is rarely the binding constraint
- `THRESHOLD_MIN_PERSONAL = 50`, `THRESHOLD_MIN_GLOBAL = 200` — first cut
- Whether to extend `GeocodeCache` with a routing variant or add a sibling `RoutingCache` table — implementation choice; both work
