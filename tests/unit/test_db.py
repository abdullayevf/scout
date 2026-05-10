from sqlalchemy import text

from apps.shared.db import build_engine


def test_build_engine_connects(pg_container):
    eng = build_engine(pg_container.get_connection_url().replace("psycopg2", "psycopg"))
    with eng.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1
