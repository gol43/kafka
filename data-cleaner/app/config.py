from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import AliasChoices, Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    service_name: str = "data-cleaner"
    log_level: str = "INFO"

    db_user: str = Field(default="quality", validation_alias="DB_USER")
    db_password: str = Field(
        default="quality",
        validation_alias=AliasChoices("DB_PASS", "DB_PASSWORD"),
    )
    db_name: str = Field(default="quality", validation_alias="DB_NAME")
    postgres_hosts: str = Field(
        default="postgres:5432", validation_alias="POSTGRES_HOSTS"
    )
    postgres_dsn_override: str | None = Field(
        default=None,
        validation_alias="POSTGRES_DSN",
        exclude=True,
    )
    postgres_schema: str = "cleaner"
    postgres_pool_size: int = Field(default=10, ge=1)
    postgres_max_overflow: int = Field(default=20, ge=0)
    postgres_pool_recycle_seconds: int = Field(default=3600, ge=60)

    cleaner_callback_urls: list[HttpUrl] = Field(default_factory=list)
    cleaner_poll_interval_seconds: float = Field(default=30, gt=0)
    cleaner_worker_batch_size: int = Field(default=10, ge=1)
    cleaner_callback_concurrency: int = Field(default=10, ge=1)
    cleaner_callback_queue_size: int = Field(default=1000, ge=1)
    cleaner_callback_timeout_seconds: float = Field(default=10, gt=0)
    ucp_base_url: str = "http://ucp:8080"
    ucp_timeout_seconds: float = Field(default=10, gt=0)
    crypto_key: str | None = None

    @property
    def postgres_dsn(self) -> str:
        if self.postgres_dsn_override:
            return self.postgres_dsn_override

        hosts = [
            host.strip() for host in self.postgres_hosts.split(",") if host.strip()
        ]
        if not hosts:
            raise ValueError("POSTGRES_HOSTS must contain at least one host")

        host_query = "&".join(f"host={quote_plus(host)}" for host in hosts)
        return (
            f"postgresql+asyncpg://{quote_plus(self.db_user)}:{quote_plus(self.db_password)}"
            f"@/{quote_plus(self.db_name)}?{host_query}&target_session_attrs=read-write"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
