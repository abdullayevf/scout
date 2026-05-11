from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import text

from apps.shared.enums import DeliveredVia, ListingState, MatchState, UserState, SearchType
from apps.shared.models import Base, Event, Listing, Match, User


@pytest.fixture(autouse=True)
def _clean_tables(engine):
    """Truncate all tables after each test so committed rows don't bleed into other test modules."""
    yield
    with engine.begin() as conn:
        conn.execute(text(
            "TRUNCATE users, listings, matches, events RESTART IDENTITY CASCADE"
        ))


def _user(db_session, tg, **kw):
    defaults = dict(
        state=UserState.ACTIVE,
        search_type=SearchType.WHOLE_APT_SOLO,
        budget_min=1_000_000, budget_max=3_000_000,
        areas=["Yunusabad"],
        axis_priority={"budget": "NICE"},
        agent_filter="agents_ok",
        preference_embedding=[0.1] * 3072,
    )
    defaults.update(kw)
    u = User(tg_user_id=tg, **defaults)
    db_session.add(u)
    db_session.flush()
    return u


def _listing(db_session, **kw):
    defaults = dict(
        source="olx", source_listing_id=kw.get("source_listing_id", "d"),
        source_category="long_term_apt",
        source_url=f"https://www.olx.uz/{kw.get('source_listing_id', 'd')}",
        title="t", description_raw="",
        state=ListingState.ACTIVE,
        price_uzs=1_500_000, rooms=2, area="Yunusabad",
        is_furnished=True,
        posted_at=datetime.now(UTC) - timedelta(hours=2),
        image_urls=[], image_phashes=[],
    )
    defaults.update(kw)
    l = Listing(**defaults)
    db_session.add(l)
    db_session.flush()
    return l


def test_digest_skips_when_no_pending(engine, db_session):
    from apps.workers.tasks.digest import digest_send_for_user
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=701)
    db_session.commit()
    with patch("apps.workers.tasks.digest.session_scope") as ss, \
         patch("apps.workers.tasks.digest.send_digest_header") as h, \
         patch("apps.workers.tasks.digest.send_match_message") as m:
        ss.return_value.__enter__.return_value = db_session
        out = digest_send_for_user.run(u.id)
    assert out["matches"] == 0
    h.assert_not_called()
    m.assert_not_called()


def test_digest_sends_top_k_for_warm_user(engine, db_session):
    from apps.workers.tasks.digest import digest_send_for_user
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=702)
    # warm user: ≥10 reactions
    for i in range(11):
        l = _listing(db_session, source_listing_id=f"warm-{i}")
        db_session.add(Match(
            user_id=u.id, listing_id=l.id,
            score=0.4, reasons=[], state=MatchState.LIKED,
        ))
    # pending matches with varying scores
    for i in range(10):
        l = _listing(db_session, source_listing_id=f"p-{i}")
        db_session.add(Match(
            user_id=u.id, listing_id=l.id,
            score=0.5 + i * 0.01, reasons=["💰 test", "📍 Юнусабад"],
            state=MatchState.PENDING,
        ))
    db_session.commit()

    with patch("apps.workers.tasks.digest.session_scope") as ss, \
         patch("apps.workers.tasks.digest.send_digest_header") as h, \
         patch("apps.workers.tasks.digest.send_match_message") as m:
        ss.return_value.__enter__.return_value = db_session
        out = digest_send_for_user.run(u.id)

    assert out["matches"] == 8
    h.assert_called_once()
    assert m.call_count == 8


def test_digest_uses_stratifier_for_cold_user(engine, db_session):
    from apps.workers.tasks.digest import digest_send_for_user
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=703, areas=["Yunusabad", "Chilanzar", "Sergeli", "Almazar"])
    areas = ["Yunusabad", "Chilanzar", "Sergeli", "Almazar"]
    for i in range(12):
        l = _listing(
            db_session, source_listing_id=f"cs-{i}",
            area=areas[i % 4], price_uzs=1_000_000 + i * 100_000,
            is_furnished=bool(i % 2),
        )
        db_session.add(Match(
            user_id=u.id, listing_id=l.id,
            score=0.5 + i * 0.01, reasons=[], state=MatchState.PENDING,
        ))
    db_session.commit()

    with patch("apps.workers.tasks.digest.session_scope") as ss, \
         patch("apps.workers.tasks.digest.send_digest_header"), \
         patch("apps.workers.tasks.digest.send_match_message") as m:
        ss.return_value.__enter__.return_value = db_session
        out = digest_send_for_user.run(u.id)

    assert out["matches"] == 8
    assert m.call_count == 8


def test_digest_filters_dead_listings(engine, db_session):
    from apps.workers.tasks.digest import digest_send_for_user
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=704)
    l_alive = _listing(db_session, source_listing_id="alive")
    l_dead = _listing(db_session, source_listing_id="dead", state=ListingState.DEAD)
    db_session.add(Match(user_id=u.id, listing_id=l_alive.id, score=0.5, reasons=[], state=MatchState.PENDING))
    db_session.add(Match(user_id=u.id, listing_id=l_dead.id, score=0.9, reasons=[], state=MatchState.PENDING))
    db_session.commit()

    with patch("apps.workers.tasks.digest.session_scope") as ss, \
         patch("apps.workers.tasks.digest.send_digest_header"), \
         patch("apps.workers.tasks.digest.send_match_message") as m:
        ss.return_value.__enter__.return_value = db_session
        out = digest_send_for_user.run(u.id)

    assert out["matches"] == 1
    sent_listing = m.call_args[0][1]
    assert sent_listing.id == l_alive.id
