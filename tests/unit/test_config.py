from apps.shared.config import Settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("POSTGRES_HOST", "db.example")
    monkeypatch.setenv("POSTGRES_PORT", "6543")
    monkeypatch.setenv("POSTGRES_DB", "x")
    monkeypatch.setenv("POSTGRES_USER", "u")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p")
    monkeypatch.setenv("REDIS_URL", "redis://r:1/0")
    monkeypatch.setenv("GOOGLE_API_KEY", "g")
    monkeypatch.setenv("YANDEX_GEOCODE_API_KEY", "y1")
    monkeypatch.setenv("YANDEX_ROUTING_API_KEY", "y2")

    s = Settings()
    assert s.postgres_dsn == "postgresql+psycopg://u:p@db.example:6543/x"
    assert s.redis_url == "redis://r:1/0"
    assert s.embedding_dim == 768
