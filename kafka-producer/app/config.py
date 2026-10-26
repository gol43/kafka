from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки ручного Kafka Producer."""

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    kafka_bootstrap_servers: str = "kafka:29092"
    kafka_topic: str = "salute-speech"
    kafka_max_message_size: int = Field(default=10_485_760, ge=1024)

    @property
    def kafka_servers(self) -> list[str]:
        return [
            value.strip()
            for value in self.kafka_bootstrap_servers.split(",")
            if value.strip()
        ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
