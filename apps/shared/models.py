from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from apps.shared.config import settings
from apps.shared.enums import (  # noqa: F401
    BathroomType,
    GenderConstraint,
    ListingState,
    OlxCategory,
    PosterRole,
    SearchType,
)


class Base(DeclarativeBase):
    pass


class Listing(Base):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    source: Mapped[str] = mapped_column(String(32), default="olx")
    source_url: Mapped[str] = mapped_column(Text, unique=True)
    source_listing_id: Mapped[str] = mapped_column(String(64), index=True)
    source_category: Mapped[str] = mapped_column(String(32))  # OlxCategory

    # raw + normalized text
    title: Mapped[str] = mapped_column(Text)
    description_raw: Mapped[str] = mapped_column(Text)
    description_ru: Mapped[str | None] = mapped_column(Text)
    language_detected: Mapped[str | None] = mapped_column(String(8))
    summary_one_line: Mapped[str | None] = mapped_column(Text)

    # price
    price_raw: Mapped[str | None] = mapped_column(String(64))
    currency_raw: Mapped[str | None] = mapped_column(String(8))
    price_uzs: Mapped[int | None] = mapped_column(BigInteger, index=True)

    # structured fields (LLM-extracted or directly parsed)
    rooms: Mapped[int | None] = mapped_column(Integer, index=True)
    floor: Mapped[int | None] = mapped_column(Integer)
    total_floors: Mapped[int | None] = mapped_column(Integer)
    is_first_floor: Mapped[bool | None] = mapped_column(Boolean)
    bathroom_type: Mapped[str | None] = mapped_column(String(16))
    is_furnished: Mapped[bool | None] = mapped_column(Boolean)
    has_parking: Mapped[bool | None] = mapped_column(Boolean)

    search_type_listing: Mapped[str | None] = mapped_column(String(32))
    gender_constraint_listing: Mapped[str | None] = mapped_column(String(8))

    poster_role: Mapped[str | None] = mapped_column(String(8))
    agent_fee_text: Mapped[str | None] = mapped_column(Text)

    # location
    area: Mapped[str | None] = mapped_column(String(64), index=True)  # tuman name
    location_text: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)

    # contact
    contact_phone_raw: Mapped[str | None] = mapped_column(String(32))
    phone_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    poster_id: Mapped[str | None] = mapped_column(String(64), index=True)

    # images
    image_urls: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    image_phashes: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list)

    # vector
    embedding: Mapped[list[float] | None] = mapped_column(Vector(settings.embedding_dim))

    # risk + state
    risk_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    suppressed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    risk_flags: Mapped[dict] = mapped_column(JSONB, default=dict)

    state: Mapped[str] = mapped_column(String(20), default=ListingState.PENDING_ENRICH, index=True)

    # dedup linkage (set when this row is collapsed into a canonical one)
    canonical_listing_id: Mapped[int | None] = mapped_column(
        BigInteger, index=True
    )

    # lifecycle timestamps
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dead_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    body_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_listings_state_active", "state", postgresql_where="state = 'active'"),
        Index("ix_listings_phone_hash_alive", "phone_hash", postgresql_where="state != 'dead'"),
        UniqueConstraint("source_url", name="uq_listings_source_url"),
    )


class GeocodeCache(Base):
    __tablename__ = "geocode_cache"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    query_norm: Mapped[str] = mapped_column(Text, unique=True, index=True)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    matched_text: Mapped[str | None] = mapped_column(Text)
    raw_response: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CurrencyRate(Base):
    __tablename__ = "currency_rates"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(8), index=True)
    rate_uzs: Mapped[float] = mapped_column(Float)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("code", "fetched_at", name="uq_rate_code_at"),
    )


class ScrapeRunHealth(Base):
    """Rolling per-category counter for httpx success rate."""
    __tablename__ = "scrape_run_health"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    success_count: Mapped[int] = mapped_column(Integer)
    failure_count: Mapped[int] = mapped_column(Integer)
    used_playwright_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
