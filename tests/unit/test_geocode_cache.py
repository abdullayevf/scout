from pathlib import Path

import respx
from httpx import Response
from sqlalchemy.orm import sessionmaker


@respx.mock
def test_geocode_caches_result(engine, monkeypatch):
    import apps.shared.db as db_module
    from apps.shared.geo.yandex import geocode
    from apps.shared.models import Base

    Base.metadata.create_all(engine)
    db_module._engine = engine
    db_module.SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    fixture = Path("tests/fixtures/yandex_geocode_yunusabad.json").read_text()
    route = respx.get("https://geocode-maps.yandex.ru/1.x/").mock(
        return_value=Response(200, text=fixture)
    )
    monkeypatch.setenv("YANDEX_GEOCODE_API_KEY", "test")

    r1 = geocode("Юнусабадский район, Ташкент")
    r2 = geocode("Юнусабадский район, Ташкент")
    assert r1.lat == r2.lat == 41.366776
    assert r1.lng == r2.lng == 69.282671
    assert route.call_count == 1  # cache hit on second call
