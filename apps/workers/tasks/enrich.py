import logging
from datetime import UTC, datetime

from sqlalchemy import select

from apps.shared.config import settings
from apps.shared.db import session_scope
from apps.shared.dedup.tiered import dedup_decide
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
                _, h = images.download_and_phash(
                    url, storage_dir=settings.image_storage_dir
                )
                phashes.append(h)
            except Exception as e:
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
            except Exception as e:
                log.warning("phone reveal failed for %s: %s", row.source_url, e)
                phone_raw = None
            if phone_raw:
                normalized = normalize_phone(phone_raw)
                row.contact_phone_raw = phone_raw
                row.phone_hash = hash_phone(normalized) if normalized else None

        # 8. risk score
        agent_kw = any(
            kw in (row.description_ru or "").lower() for kw in AGENT_KEYWORDS
        )
        from sqlalchemy import func

        phone_seen_unrelated = 0
        if row.phone_hash:
            phone_seen_unrelated = s.execute(
                select(func.count(Listing.id)).where(
                    Listing.phone_hash == row.phone_hash,
                    Listing.id != row.id,
                )
            ).scalar_one()
        # cross-phash collision: any other listing shares any of our phashes
        # with a different phone_hash
        cross_collision = False
        if phashes and row.phone_hash:
            cross_collision = bool(
                s.execute(
                    select(Listing.id)
                    .where(
                        Listing.image_phashes.overlap(phashes),
                        Listing.phone_hash != row.phone_hash,
                        Listing.id != row.id,
                    )
                    .limit(1)
                ).first()
            )

        # area median + stdev placeholders — Plan 1 leaves these None until
        # we have enough data
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

        # 9a. dedup — set canonical_listing_id if a match is found
        dedup_decide(s, row)

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
        row.enriched_at = datetime.now(UTC)

    return {"ok": True, "listing_id": listing_id}


@app.task(name="enrich.listing", bind=True, max_retries=3, default_retry_delay=120)
def enrich_listing(self, listing_id: int) -> dict:
    return _enrich_one(listing_id)


@app.task(name="enrich.listings.pending")
def enrich_pending_listings(batch_size: int = 50) -> dict:
    """Find pending listings and dispatch one enrich task per row."""
    with session_scope() as s:
        ids = (
            s.execute(
                select(Listing.id)
                .where(Listing.state == ListingState.PENDING_ENRICH)
                .order_by(Listing.created_at.asc())
                .limit(batch_size)
            )
            .scalars()
            .all()
        )
    for lid in ids:
        enrich_listing.delay(lid)
    return {"dispatched": len(ids)}
