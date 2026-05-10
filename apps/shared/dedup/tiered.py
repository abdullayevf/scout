import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.shared.models import Listing

_NON_ALNUM = re.compile(r"[^\wа-яёҳқғўa-z0-9]+", re.IGNORECASE)  # noqa: RUF001
# Common street/address-type abbreviations to strip before comparison
_STREET_PREFIX = re.compile(
    r"\b(ул|пр|пер|б-р|бул|пл|наб|ш|мкр|кв|д|кор|корп|стр|г)\.?\s*",  # noqa: RUF001
    re.IGNORECASE,
)


def _normalize_address(s: str | None) -> str:
    if not s:
        return ""
    s = s.lower()
    s = _STREET_PREFIX.sub(" ", s)
    return _NON_ALNUM.sub(" ", s).strip()


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
