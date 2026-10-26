from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    service_name: str = "kafka-consumer"
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
    postgres_schema: str = "kafka"
    postgres_pool_size: int = Field(default=10, ge=1)
    postgres_max_overflow: int = Field(default=20, ge=0)
    postgres_pool_recycle_seconds: int = Field(default=3600, ge=60)

    kafka_bootstrap_servers: str = "kafka:9092"
    kafka_topic: str = "salute-speech"
    kafka_group_id: str = "quality-kafka-consumer"
    kafka_max_message_size: int = Field(default=10_485_760, ge=1024)

    cleaner_base_url: str = "http://data-cleaner:8080"
    cleaner_timeout_seconds: float = Field(default=10.0, gt=0)

    chunk_storage_encrypted: bool = False
    cleaner_request_encrypted: bool = False
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

    @property
    def kafka_servers(self) -> list[str]:
        return [
            server.strip()
            for server in self.kafka_bootstrap_servers.split(",")
            if server.strip()
        ]

    @model_validator(mode="after")
    def encryption_requires_key(self) -> "Settings":
        encryption_enabled = (
            self.chunk_storage_encrypted or self.cleaner_request_encrypted
        )
        if encryption_enabled and not self.crypto_key:
            raise ValueError("CRYPTO_KEY is required when encryption is enabled")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
