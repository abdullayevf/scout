from datetime import UTC, datetime

from sqlalchemy.orm import sessionmaker

from apps.shared.dedup.tiered import find_canonical_for
from apps.shared.enums import ListingState
from apps.shared.models import Base, Listing


def _mk(s, **kw):
    defaults = dict(
        source="olx", source_listing_id=kw.get("source_listing_id", "x"),
        source_category="long_term_apt",
        title="t", description_raw="", state=ListingState.ACTIVE,
        last_seen_at=datetime.now(UTC),
        image_urls=[], image_phashes=[],
    )
    defaults.update(kw)
    row = Listing(**defaults)
    s.add(row)
    s.flush()
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
    _mk(s, source_url="https://www.olx.uz/e", source_listing_id="e", phone_hash="h2", price_uzs=8_000_000, rooms=2, area="Yunusabad")
    b = _mk(s, source_url="https://www.olx.uz/f", source_listing_id="f", phone_hash="h3", price_uzs=12_000_000, rooms=4, area="Chilanzar")
    s.commit()

    assert find_canonical_for(s, b) is None
