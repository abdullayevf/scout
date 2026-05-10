import asyncio
import logging
from datetime import UTC, datetime

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
    OlxCategory.LONG_TERM: (
        "https://www.olx.uz/nedvizhimost/kvartiry/arenda-dolgosrochnaya/"
    ),
    OlxCategory.ROOMS: (
        "https://www.olx.uz/nedvizhimost/komnaty/"
    ),
    OlxCategory.DAILY: (
        "https://www.olx.uz/nedvizhimost/kvartiry/arenda-kratkosrochnaya/"
    ),
    OlxCategory.LOOKING_FOR: (
        "https://www.olx.uz/nedvizhimost/snimu/"
    ),
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
                        .values(last_seen_at=datetime.now(UTC))
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
                        last_seen_at=datetime.now(UTC),
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
        return {
            "category": category,
            "ok": True,
            "discovered": len(cards),
            "inserted": inserted,
        }
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
            row.last_seen_at = datetime.now(UTC)
            return {"ok": True, "listing_id": listing_id}
    finally:
        await client.aclose()
