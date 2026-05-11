from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from apps.shared.enums import (
    GenderConstraint, ListingState, MatchState,
    PosterRole, SearchType, UserState,
)
from apps.shared.models import Base, Listing, Match, User


def _user(db_session, tg, **kw):
    defaults = dict(
        state=UserState.ACTIVE,
        search_type=SearchType.WHOLE_APT_SOLO,
        budget_min=1_000_000, budget_max=2_000_000,
        rooms=None,
        areas=["Yunusabad"],
        axis_priority={"budget": "MUST", "area": "NICE", "rooms": "NICE"},
        agent_filter="agents_ok",
        gender_pref=GenderConstraint.ANY,
        preference_embedding=[0.1] * 3072,
    )
    defaults.update(kw)
    u = User(tg_user_id=tg, **defaults)
    db_session.add(u)
    db_session.flush()
    return u


def _listing(db_session, **kw):
    defaults = dict(
        source="olx", source_listing_id=str(kw.get("id_suffix", "x")),
        source_category="long_term_apt",
        source_url=f"https://www.olx.uz/{kw.get('id_suffix', 'x')}",
        title="t", description_raw="", description_ru="чистая квартира",
        state=ListingState.ACTIVE,
        price_uzs=1_500_000, rooms=2, area="Yunusabad",
        search_type_listing=SearchType.WHOLE_APT_SOLO,
        gender_constraint_listing=GenderConstraint.ANY,
        poster_role=PosterRole.OWNER, phone_hash="ph",
        posted_at=datetime.now(UTC) - timedelta(minutes=15),
        embedding=[0.1] * 3072,
        risk_score=0, suppressed=False,
        is_furnished=True, has_parking=True, is_first_floor=False,
        bathroom_type="private",
        image_urls=[], image_phashes=[],
    )
    kw.pop("id_suffix", None)
    defaults.update(kw)
    l = Listing(**defaults)
    db_session.add(l)
    db_session.flush()
    return l


def test_fanout_inserts_matches_for_eligible_users(engine, db_session):
    from apps.workers.tasks.match import match_fanout_listing
    Base.metadata.create_all(engine)
    u1 = _user(db_session, tg=701)
    u2 = _user(db_session, tg=702, state=UserState.PAUSED)
    l = _listing(db_session, id_suffix="abc")
    db_session.commit()

    with patch("apps.workers.tasks.match.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        with patch("apps.workers.tasks.match.match_alert_instant"):
            match_fanout_listing.run(l.id)

    matches = db_session.query(Match).filter_by(listing_id=l.id).all()
    user_ids = {m.user_id for m in matches}
    assert u1.id in user_ids
    assert u2.id not in user_ids


def test_fanout_skips_suppressed_listing(engine, db_session):
    from apps.workers.tasks.match import match_fanout_listing
    Base.metadata.create_all(engine)
    _user(db_session, tg=801)
    l = _listing(db_session, id_suffix="sup", suppressed=True)
    db_session.commit()

    with patch("apps.workers.tasks.match.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        result = match_fanout_listing.run(l.id)
    assert result["ok"] is False
    assert db_session.query(Match).count() == 0


def test_fanout_skips_canonical_pointer(engine, db_session):
    from apps.workers.tasks.match import match_fanout_listing
    Base.metadata.create_all(engine)
    _user(db_session, tg=802)
    canonical = _listing(db_session, id_suffix="canon")
    db_session.flush()
    dup = _listing(db_session, id_suffix="dup", canonical_listing_id=canonical.id)
    db_session.commit()

    with patch("apps.workers.tasks.match.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        result = match_fanout_listing.run(dup.id)
    assert result["ok"] is False


def test_fanout_respects_insert_threshold(engine, db_session):
    from apps.workers.tasks.match import match_fanout_listing
    Base.metadata.create_all(engine)
    u = _user(db_session, tg=803, preference_embedding=[0.0] * 3071 + [1.0])
    l = _listing(
        db_session, id_suffix="lo",
        embedding=[1.0] + [0.0] * 3071,
        risk_score=3,
        posted_at=datetime.now(UTC) - timedelta(days=60),
    )
    db_session.commit()

    with patch("apps.workers.tasks.match.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        with patch("apps.workers.tasks.match.match_alert_instant"):
            match_fanout_listing.run(l.id)

    assert db_session.query(Match).filter_by(listing_id=l.id).count() == 0
