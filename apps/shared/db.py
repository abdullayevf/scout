from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from apps.shared.config import settings


def build_engine(dsn: str | None = None) -> Engine:
    return create_engine(
        dsn or settings.postgres_dsn,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )


_engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None


def init_engine() -> None:
    global _engine, SessionLocal
    _engine = build_engine()
    SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    if SessionLocal is None:
        init_engine()
    assert SessionLocal is not None
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
