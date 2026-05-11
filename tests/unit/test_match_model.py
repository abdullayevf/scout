import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from apps.shared.enums import MatchState, DeliveredVia
from apps.shared.models import Base, Match


def test_match_table_exists(engine):
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    assert "matches" in insp.get_table_names()


def test_match_create_minimal(engine, db_session):
    Base.metadata.create_all(engine)
    m = Match(user_id=1, listing_id=1, score=0.5, reasons=["💰 test"])
    db_session.add(m)
    db_session.flush()
    assert m.id is not None
    assert m.state == "pending"
    assert m.delivered_via is None


def test_match_unique_user_listing(engine, db_session):
    Base.metadata.create_all(engine)
    db_session.add(Match(user_id=2, listing_id=2, score=0.5, reasons=[]))
    db_session.flush()
    db_session.add(Match(user_id=2, listing_id=2, score=0.6, reasons=[]))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_match_state_enum_values():
    assert MatchState.PENDING == "pending"
    assert MatchState.SENT == "sent"
    assert MatchState.LIKED == "liked"
    assert MatchState.DISLIKED == "disliked"
    assert MatchState.CONTACTED == "contacted"
    assert MatchState.RENTED == "rented"
    assert MatchState.DEAD == "dead"


def test_delivered_via_enum_values():
    assert DeliveredVia.DIGEST == "digest"
    assert DeliveredVia.INSTANT == "instant"
