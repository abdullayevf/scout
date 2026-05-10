import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def pg_container():
    with PostgresContainer("pgvector/pgvector:pg16") as c:
        yield c


@pytest.fixture(scope="session")
def engine(pg_container):
    eng = create_engine(pg_container.get_connection_url().replace("psycopg2", "psycopg"))
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    yield eng
    eng.dispose()


@pytest.fixture
def db_session(engine) -> Session:
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()
