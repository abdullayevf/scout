from functools import cached_property

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    env: str = "dev"

    postgres_host: str
    postgres_port: int = 5432
    postgres_db: str
    postgres_user: str
    postgres_password: str

    redis_url: str

    google_api_key: str
    gemini_model: str = "gemini-2.5-flash"
    gemini_embed_model: str = "text-embedding-004"
    embedding_dim: int = 768

    yandex_geocode_api_key: str
    yandex_routing_api_key: str

    image_storage_dir: str = "/data/images"

    olx_base_url: str = "https://www.olx.uz"
    scrape_httpx_failure_threshold: float = 0.20
    scrape_proxy_url: str = ""

    enrichment_workers: int = 4

    @cached_property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()  # type: ignore[call-arg]
