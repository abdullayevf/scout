import logging
from datetime import datetime, timedelta

from sqlalchemy import update

from apps.shared.db import session_scope
from apps.shared.enums import ListingState
from apps.shared.models import Listing
from apps.workers.celery_app import app

log = logging.getLogger(__name__)


@app.task(name="purge.listings.dead")
def purge_dead_listing_bodies(older_than_days: int = 60) -> dict:
    """Strip raw body + raw phone from listings dead for > N days. pHash + phone_hash retained."""
    cutoff = datetime.now(datetime.UTC) - timedelta(days=older_than_days)
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
                body_purged_at=datetime.now(datetime.UTC),
            )
        )
        return {"purged": result.rowcount}
