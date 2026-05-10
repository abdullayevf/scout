import pytest
from sqlalchemy import inspect, text
from apps.shared.models import Base, User, Event
from apps.shared.enums import UserState


def test_user_table_exists(engine):
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    assert "users" in insp.get_table_names()


def test_event_table_exists(engine):
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    assert "events" in insp.get_table_names()


def test_user_create_minimal(db_session):
    Base.metadata.create_all(db_session.bind)
    u = User(tg_user_id=111, state=UserState.ONBOARDING)
    db_session.add(u)
    db_session.flush()
    assert u.id is not None
    assert u.state == "onboarding"


def test_user_tg_user_id_unique(db_session):
    from sqlalchemy.exc import IntegrityError
    Base.metadata.create_all(db_session.bind)
    db_session.add(User(tg_user_id=222, state=UserState.ONBOARDING))
    db_session.flush()
    db_session.add(User(tg_user_id=222, state=UserState.ONBOARDING))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_event_create(db_session):
    Base.metadata.create_all(db_session.bind)
    e = Event(kind="onboarding_started", user_id=333)
    db_session.add(e)
    db_session.flush()
    assert e.id is not None
