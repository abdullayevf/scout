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
    DeliveredVia,
    GenderConstraint,
    ListingState,
    MatchState,
    OlxCategory,
    PosterRole,
    SearchType,
    UserState,
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


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    tg_username: Mapped[str | None] = mapped_column(Text)

    search_type: Mapped[str | None] = mapped_column(String(32))
    gender_pref: Mapped[str | None] = mapped_column(String(8))
    agent_filter: Mapped[str | None] = mapped_column(String(16))
    budget_min: Mapped[int | None] = mapped_column(BigInteger)
    budget_max: Mapped[int | None] = mapped_column(BigInteger)
    rooms: Mapped[int | None] = mapped_column(Integer)
    areas: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    move_in_window: Mapped[str | None] = mapped_column(String(16))

    commute_origin: Mapped[str | None] = mapped_column(Text)
    commute_origin_lat: Mapped[float | None] = mapped_column(Float)
    commute_origin_lng: Mapped[float | None] = mapped_column(Float)
    commute_max_minutes: Mapped[int | None] = mapped_column(Integer)
    commute_mode: Mapped[str | None] = mapped_column(String(8))

    dealbreakers: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    dealbreaker_keywords: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    axis_priority: Mapped[dict] = mapped_column(JSONB, default=dict)

    tradeoff_hint_text: Mapped[str | None] = mapped_column(Text)
    unacceptable_text: Mapped[str | None] = mapped_column(Text)
    instant_reject_text: Mapped[str | None] = mapped_column(Text)
    preference_embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dim)
    )

    negative_area_mask: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    distrust_set: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    seen_set: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), default=list)
    top_1pct_threshold: Mapped[float | None] = mapped_column(Float)

    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default=UserState.ONBOARDING, index=True
    )
    paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    listing_id: Mapped[int | None] = mapped_column(BigInteger)
    match_id: Mapped[int | None] = mapped_column(BigInteger)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    listing_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    score: Mapped[float] = mapped_column(Float, nullable=False)
    reasons: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, nullable=False)

    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default=MatchState.PENDING
    )
    delivered_via: Mapped[str | None] = mapped_column(String(8))
    dislike_reason: Mapped[str | None] = mapped_column(String(32))

    liked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disliked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    chase_48h_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    chase_48h_done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    chase_5d_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    chase_5d_done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "listing_id", name="uq_matches_user_listing"),
        Index("ix_matches_user_state_score", "user_id", "state", "score"),
        Index(
            "ix_matches_user_delivered",
            "user_id",
            "delivered_via",
            "created_at",
        ),
        Index(
            "ix_matches_pending_score",
            "state",
            "score",
            postgresql_where="state = 'pending'",
        ),
    )
