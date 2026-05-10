from datetime import UTC, datetime

from sqlalchemy.orm import sessionmaker

from apps.shared.enums import ListingState
from apps.shared.models import Base, Listing


def test_insert_and_query_listing(engine):
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    s = SessionLocal()

    row = Listing(
        source="olx",
        source_url="https://www.olx.uz/d/obyavlenie/test-1",
        source_listing_id="test-1",
        source_category="long_term_apt",
        title="2-комн. в Юнусабаде",
        description_raw="...",
        state=ListingState.PENDING_ENRICH,
        last_seen_at=datetime.now(UTC),
        image_urls=[],
        image_phashes=[],
    )
    s.add(row)
    s.commit()

    fetched = s.query(Listing).filter_by(source_listing_id="test-1").one()
    assert fetched.title == "2-комн. в Юнусабаде"
    s.close()
