import json
from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import quote_plus

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки Analyzer, которые один раз загружаются из ENV."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    service_name: str = "analyzer"
    log_level: str = "INFO"
    log_llm_responses: bool = True

    db_user: str = Field(default="quality", validation_alias="DB_USER")
    db_password: str = Field(
        default="quality",
        validation_alias=AliasChoices("DB_PASS", "DB_PASSWORD"),
    )
    db_name: str = Field(default="quality", validation_alias="DB_NAME")
    postgres_hosts: str = Field(
        default="postgres:5432",
        validation_alias="POSTGRES_HOSTS",
    )
    postgres_dsn_override: str | None = Field(
        default=None,
        validation_alias="POSTGRES_DSN",
        exclude=True,
    )
    postgres_schema: str = "analyzer"
    postgres_pool_size: int = Field(default=10, ge=1)
    postgres_max_overflow: int = Field(default=20, ge=0)
    postgres_pool_recycle_seconds: int = Field(default=3600, ge=60)

    worker_poll_interval_seconds: float = Field(default=30, gt=0)
    worker_claim_limit: int = Field(default=100, ge=1)
    dialog_pipeline_concurrency: int = Field(default=10, ge=1)
    min_dialog_duration_seconds: int = Field(default=50, ge=0)
    data_ttl_days: int = Field(default=183, ge=1)
    calendar_filter_enabled: bool = True
    analyzed_manager_ids: Annotated[set[str], NoDecode] = Field(
        default_factory=set,
        validation_alias="ANALYZED_MANAGER_IDS",
    )
    prompt_analyzer_manager_ids: Annotated[set[str], NoDecode] = Field(
        default_factory=set,
        validation_alias="PROMPT_ANALYZER_MANAGER_IDS",
    )
    audio_analyzer_manager_ids: Annotated[set[str], NoDecode] = Field(
        default_factory=set,
        validation_alias="AUDIO_ANALYZER_MANAGER_IDS",
    )
    factor_analyzer_manager_ids: Annotated[set[str], NoDecode] = Field(
        default_factory=set,
        validation_alias="FACTOR_ANALYZER_MANAGER_IDS",
    )
    audio_analyzer_url: str | None = None
    factor_analyzer_url: str | None = None
    external_analyzer_timeout_seconds: float = Field(default=300, gt=0)

    llm_provider: Literal["gigachat", "ollama"] = "gigachat"

    gigachat_auth_url: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    gigachat_base_url: str = "https://api.giga.chat/v1"
    gigachat_credentials: str = ""
    gigachat_scope: str = "GIGACHAT_API_CORP"
    gigachat_model: str = "GigaChat-2-Pro"
    gigachat_verify_ssl: bool = True
    gigachat_cert_file: str | None = None
    gigachat_key_file: str | None = None
    gigachat_timeout_seconds: float = Field(default=120, gt=0)
    gigachat_max_concurrency: int = Field(default=1, ge=1)
    gigachat_max_attempts: int = Field(default=5, ge=1)
    gigachat_retry_base_seconds: float = Field(default=1, gt=0)
    gigachat_temperature: float | None = Field(default=0.1, ge=0, le=2)
    gigachat_top_p: float | None = Field(default=None, ge=0, le=1)
    gigachat_max_output_tokens: int = Field(default=8000, ge=256)
    gigachat_repetition_penalty: float = Field(default=1.0, ge=0)
    gigachat_max_input_tokens: int = Field(default=116000, ge=1024)
    gigachat_prompt_reserve_tokens: int = Field(default=2000, ge=0)
    gigachat_output_reserve_tokens: int = Field(default=8000, ge=256)
    aggregation_max_batch_items: int = Field(default=15, ge=2)

    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "qwen3:4b-instruct"
    ollama_keep_alive: str = "30m"
    ollama_chars_per_token: float = Field(default=2.0, gt=0)
    active_criteria_codes: Annotated[set[str], NoDecode] = Field(
        default_factory=set,
        validation_alias="ACTIVE_CRITERIA_CODES",
    )
    deposit_analysis_enabled: bool = True

    criteria_version: str = "prompt-4q-v1"
    prompt_version: str = "prompt-4q-v1"
    report_version: str = "v1"
    dashboard_enabled: bool = True
    dashboard_cron_hour_utc: int = Field(default=18, ge=0, le=23)
    dashboard_wait_interval_seconds: float = Field(default=30, gt=0)
    metric_rolling_window_days: int = Field(default=30, ge=1)
    risk_rolling_window_days: int = Field(default=10, ge=1)
    strength_min_percent: float = Field(default=80, ge=0, le=100)
    strengths_limit: int = Field(default=3, ge=1)
    improvements_limit: int = Field(default=3, ge=1)
    risk_clients_limit: int = Field(default=5, ge=1)
    latest_communications_limit: int = Field(default=5, ge=1)
    communications_max_limit: int = Field(default=100, ge=1)
    metric_failed_communications_limit: int = Field(default=3, ge=1)
    metric_weekly_points_limit: int = Field(default=4, ge=1)
    critical_score_cap: float = Field(default=80, ge=0, le=100)
    empty_score_value: float = Field(default=0, ge=0, le=100)
    test_data_api_enabled: bool = False
    test_data_default_days: int = Field(default=45, ge=5, le=183)

    @property
    def postgres_dsn(self) -> str:
        if self.postgres_dsn_override:
            return self.postgres_dsn_override

        hosts = [
            host.strip() for host in self.postgres_hosts.split(",") if host.strip()
        ]
        if not hosts:
            raise ValueError("POSTGRES_HOSTS должен содержать хотя бы один адрес")

        host_query = "&".join(f"host={quote_plus(host)}" for host in hosts)
        return (
            f"postgresql+asyncpg://{quote_plus(self.db_user)}:{quote_plus(self.db_password)}"
            f"@/{quote_plus(self.db_name)}?{host_query}&target_session_attrs=read-write"
        )

    def analyzers_for(self, manager_id: str) -> tuple[str, ...] | None:
        """Возвращает обязательную цепочку анализаторов или отказывает во входе."""

        if manager_id not in self.analyzed_manager_ids:
            return None

        analyzers: list[str] = []
        if manager_id in self.prompt_analyzer_manager_ids:
            analyzers.append("prompt")
        if manager_id in self.audio_analyzer_manager_ids:
            analyzers.append("audio")
        if manager_id in self.factor_analyzer_manager_ids:
            analyzers.append("factor")
        return tuple(analyzers)

    @property
    def selected_llm_model(self) -> str:
        """Возвращает модель выбранного через ENV LLM-провайдера."""

        if self.llm_provider == "ollama":
            return self.ollama_model
        return self.gigachat_model

    @field_validator(
        "analyzed_manager_ids",
        "prompt_analyzer_manager_ids",
        "audio_analyzer_manager_ids",
        "factor_analyzer_manager_ids",
        mode="before",
    )
    @classmethod
    def parse_manager_ids(cls, value):
        """Разрешает задавать set как JSON-массив или строку через запятую."""

        if value is None or value == "":
            return set()
        if isinstance(value, str):
            items = (
                json.loads(value)
                if value.lstrip().startswith("[")
                else value.split(",")
            )
            return {str(item).strip().zfill(8) for item in items if str(item).strip()}
        return value

    @field_validator("active_criteria_codes", mode="before")
    @classmethod
    def parse_criteria_codes(cls, value):
        """Разрешает задавать коды критериев JSON-массивом или через запятую."""

        if value is None or value == "":
            return set()
        if isinstance(value, str):
            items = (
                json.loads(value)
                if value.lstrip().startswith("[")
                else value.split(",")
            )
            return {str(item).strip() for item in items if str(item).strip()}
        return value

    @model_validator(mode="after")
    def validate_sampling_parameters(self) -> "Settings":
        if self.gigachat_temperature is not None and self.gigachat_top_p is not None:
            raise ValueError(
                "Нужно настроить только один параметр: GIGACHAT_TEMPERATURE или GIGACHAT_TOP_P"
            )
        configured = (
            self.prompt_analyzer_manager_ids
            | self.audio_analyzer_manager_ids
            | self.factor_analyzer_manager_ids
        )
        unknown = configured - self.analyzed_manager_ids
        without_profile = self.analyzed_manager_ids - configured
        without_prompt = self.analyzed_manager_ids - self.prompt_analyzer_manager_ids
        if unknown:
            raise ValueError(
                f"Профиль задан для менеджеров вне ANALYZED_MANAGER_IDS: {sorted(unknown)}"
            )
        if without_profile:
            raise ValueError(
                f"Для менеджеров не назначен ни один анализатор: {sorted(without_profile)}"
            )
        if without_prompt:
            raise ValueError(
                "Prompt Analyzer с гигиеной, вкладами и рисками обязателен для "
                f"менеджеров: {sorted(without_prompt)}"
            )
        if self.audio_analyzer_manager_ids and not self.audio_analyzer_url:
            raise ValueError("Для Audio Analyzer требуется AUDIO_ANALYZER_URL")
        if self.factor_analyzer_manager_ids and not self.factor_analyzer_url:
            raise ValueError("Для Factor Analyzer требуется FACTOR_ANALYZER_URL")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
