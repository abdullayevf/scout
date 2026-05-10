# Plan 1 — Live Smoke Test Runbook

Run once before signing off Plan 1 as complete. Requires real API keys in `.env`.

## Prerequisites

- Fill `GOOGLE_API_KEY`, `YANDEX_GEOCODE_API_KEY`, `YANDEX_ROUTING_API_KEY` in `.env`
- Docker running

## Steps

### 1. Bring up the full stack

```bash
docker compose up -d
```

### 2. Trigger one full cycle manually

```bash
docker compose exec worker python -c "
from apps.workers.tasks.scrape import scrape_olx_category
from apps.workers.tasks.enrich import enrich_pending_listings
print('scrape:', scrape_olx_category.apply(args=('long_term_apt',)).get())
print('enrich dispatch:', enrich_pending_listings.apply(args=(20,)).get())
"
sleep 60
```

### 3. Check DB state

```bash
docker compose exec postgres psql -U scout -d scout -c "
SELECT
  count(*) FILTER (WHERE state='pending_enrich') AS pending,
  count(*) FILTER (WHERE state='active' AND NOT suppressed) AS active_clean,
  count(*) FILTER (WHERE suppressed) AS suppressed,
  count(*) FILTER (WHERE canonical_listing_id IS NOT NULL) AS deduped
FROM listings;
"
```

### 4. Eyeball one enriched row

```bash
docker compose exec postgres psql -U scout -d scout -c "
SELECT id, title, area, price_uzs, search_type_listing, poster_role, risk_score, risk_flags
FROM listings WHERE state='active' ORDER BY id DESC LIMIT 5;
"
```

## Sign-off Criteria

Plan 1 is complete when **all** of the following hold:

- [ ] `scrape_olx_category('long_term_apt')` populates ≥ 20 rows in one run
- [ ] `enrich_pending_listings(20)` flips ≥ 18 rows to `active` (≥ 90% success rate)
- [ ] At least one row has `risk_score > 0` and non-empty `risk_flags`
- [ ] At least one row has `canonical_listing_id` set (dedup is wired)
- [ ] All unit + integration tests pass: `uv run pytest -v`
- [ ] Beat fires automatically (let it run 15 min, watch logs)

## After sign-off

```bash
git tag plan-1-foundation-ingestion
```
