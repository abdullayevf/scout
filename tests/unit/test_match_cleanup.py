"""Tests for match_cleanup_dead task.

Each test begins with a clean slate (all matches wiped) to prevent
cross-test bleed in the shared postgres test container.
"""
from sqlalchemy import delete
from unittest.mock import patch

import pytest

from apps.shared.enums import ListingState, MatchState
from apps.shared.models import Base, Listing, Match


def _listing(db_session, state, suffix):
    l = Listing(
        source_url=f"https://www.olx.uz/{suffix}",
        source_listing_id=suffix,
        source_category="long_term_apt",
        title="t", description_raw="", state=state,
        image_urls=[], image_phashes=[],
    )
    db_session.add(l)
    db_session.flush()
    return l


@pytest.fixture(autouse=True)
def wipe_matches(db_session):
    """Delete all match rows before each test to avoid cross-test bleed."""
    db_session.execute(delete(Match))
    db_session.commit()
    yield
    db_session.execute(delete(Match))
    db_session.commit()


def test_cleanup_marks_dead_listing_matches_dead(engine, db_session):
    from apps.workers.tasks.match import match_cleanup_dead
    Base.metadata.create_all(engine)
    l_dead = _listing(db_session, ListingState.DEAD, "dead-cl")
    l_alive = _listing(db_session, ListingState.ACTIVE, "alive-cl")
    m_dead = Match(user_id=1, listing_id=l_dead.id, score=0.5, reasons=[], state=MatchState.PENDING)
    m_alive = Match(user_id=1, listing_id=l_alive.id, score=0.5, reasons=[], state=MatchState.PENDING)
    db_session.add_all([m_dead, m_alive])
    db_session.commit()

    with patch("apps.workers.tasks.match.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        result = match_cleanup_dead.run()

    db_session.refresh(m_dead)
    db_session.refresh(m_alive)
    assert m_dead.state == MatchState.DEAD
    assert m_alive.state == MatchState.PENDING
    assert result["updated"] == 1


def test_cleanup_skips_non_pending_matches(engine, db_session):
    from apps.workers.tasks.match import match_cleanup_dead
    Base.metadata.create_all(engine)
    l_dead = _listing(db_session, ListingState.DEAD, "dead-cl2")
    m_sent = Match(user_id=2, listing_id=l_dead.id, score=0.5, reasons=[], state=MatchState.SENT)
    db_session.add(m_sent)
    db_session.commit()

    with patch("apps.workers.tasks.match.session_scope") as ss:
        ss.return_value.__enter__.return_value = db_session
        result = match_cleanup_dead.run()

    db_session.refresh(m_sent)
    assert m_sent.state == MatchState.SENT  # unchanged — only PENDING matches are cleaned up
    assert result["updated"] == 0
