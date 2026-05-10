import asyncio
import logging
from datetime import datetime

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
                        .values(state=ListingState.DEAD, dead_at=datetime.now(datetime.UTC))
                    )
                    flipped += 1
                else:
                    s.execute(
                        Listing.__table__.update()
                        .where(Listing.id == lid)
                        .values(last_seen_at=datetime.now(datetime.UTC))
                    )
        return {"checked": len(ids_urls), "flipped_dead": flipped}
    finally:
        await client.aclose()


@app.task(name="recheck.listings.active")
def recheck_active(batch_size: int = 200) -> dict:
    return asyncio.run(_recheck_async(batch_size=batch_size))
