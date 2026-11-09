import logging
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import yaml

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = Field(alias="APP_ENV")
    app_name: str = Field(alias="APP_NAME")
    app_api_prefix: str = Field(alias="APP_API_PREFIX")

    # Логирование
    log_level: str = Field(alias="LOGGER_LEVEL")
    log_file_handler_enabled: bool = Field(alias="LOG_FILE_HANDLER_ENABLED")
    log_max_bytes: int = Field(alias="LOG_MAX_BYTES")
    log_backup_count: int = Field(alias="LOG_BACKUP_COUNT")
    log_total_size_cap: int = Field(alias="LOG_TOTAL_SIZE_CAP")
    log_file_path: str = Field(alias="LOG_PATH")
    debug: bool = Field(default=False, alias="LOGGER_DEBUG")

    json_mdc_mapping: dict[str, str] = Field(default={"rqUId": "request_id", "communicationId": "call_id"}, alias="JSON_MDC_MAPPING")
    context_vars: list[str] = Field(default=["request_id", "call_id", "manager_id"], alias="CONTEXT_VARS")


    db_user: str = Field(default="", alias="DB_USER")
    db_password: str = Field(default="", alias="DB_PASS")
    postgres_hosts: str = Field(default="localhost:5432", alias="POSTGRES_HOSTS")
    db_name: str = Field(alias="DB_NAME")

    postgres_pool_size: int = Field(alias="POSTGRES_POOL_SIZE")
    postgres_max_overflow: int = Field(alias="POSTGRES_MAX_OVERFLOW")

    @property
    def postgres_dsn(self) -> str:
        """Формирует multihost DSN для asyncpg — оба хоста, asyncpg сам выберет writable."""
        hosts = [h.strip() for h in self.postgres_hosts.split(",")]
        if not hosts:
            raise ValueError("POSTGRES_HOSTS is empty")

        host_params = "&".join([f"host={h}" for h in hosts])
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}@/{self.db_name}"
            f"?{host_params}&target_session_attrs=read-write"
        )

    encryption_key: str = Field(alias="ENCRYPTION_KEY")
    encrypt_client_fio: bool = Field(default=True, alias="ENCRYPT_CLIENT_FIO")
    subscribers_config_path: str = Field(default="app/utils/subscribers.yaml", alias="SUBSCRIBERS_CONFIG_PATH")
    callback_timeout_seconds: float = Field(default=15, alias="CALLBACK_TIMEOUT_SECONDS")
    callback_max_attempts: int = Field(default=5, alias="CALLBACK_MAX_ATTEMPTS")
    callback_retry_seconds: int = Field(default=60, alias="CALLBACK_RETRY_SECONDS")
    worker_poll_seconds: float = Field(default=10, alias="WORKER_POLL_SECONDS")
    worker_stale_seconds: int = Field(default=1800, alias="WORKER_STALE_SECONDS")
    data_ttl_days: int = Field(default=183, alias="DATA_TTL_DAYS")
    ai_q_score_callback_enabled: bool = Field(default=False, alias="AI_Q_SCORE_CALLBACK_ENABLED")
    ai_q_score_callback_url: str = Field(default="", alias="AI_Q_SCORE_CALLBACK_URL")
    call_summarization_callback_enabled: bool = Field(default=False, alias="CALL_SUMMARIZATION_CALLBACK_ENABLED")
    call_summarization_callback_url: str = Field(default="", alias="CALL_SUMMARIZATION_CALLBACK_URL")
    ai_mentor_insight_callback_enabled: bool = Field(default=False, alias="AI_MENTOR_INSIGHT_CALLBACK_ENABLED")

    def subscribers(self) -> list[dict]:
        path = Path(self.subscribers_config_path)
        content = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        result = []
        for item in content.get("subscribers", []):
            if not getattr(self, item["enabled_env"].lower(), False):
                continue
            if item["contract"] not in {"ai_q_score", "call_summarization", "ai_mentor_insight"}:
                raise ValueError(f"Unknown subscriber contract: {item['contract']}")
            subscriber = {"name": item["name"], "contract": item["contract"]}
            if "url_field" in item:
                subscriber["url_field"] = item["url_field"]
                subscriber["append_call_id"] = item.get("append_call_id", False)
            else:
                url = getattr(self, item["url_env"].lower(), "").strip()
                if not url or not url.startswith(("http://", "https://")):
                    raise ValueError(f"Missing callback URL for {item['name']}")
                subscriber["url"] = url
            result.append(subscriber)
        return result

    # Prometheus / Management Server
    management_port: int = Field(default=8081, alias="MANAGEMENT_PORT")
    prometheus_path: str = Field(default="/management-data-cleaner/actuator/prometheus", alias="PROMETHEUS_PATH")
    # 3213

@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    return settings
