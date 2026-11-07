from functools import lru_cache
import json
from typing import Annotated
from urllib.parse import quote_plus

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки Analyzer, которые один раз загружаются из ENV."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # App
    app_name: str = Field(alias="APP_NAME")
    app_api_prefix: str = Field(alias="APP_API_PREFIX")

    # Logger
    debug: bool = Field(default=False, alias="LOGGER_DEBUG")
    log_level: str = Field(alias="LOGGER_LEVEL")
    log_file_handler_enabled: bool = Field(alias="LOG_FILE_HANDLER_ENABLED")
    log_max_bytes: int = Field(alias="LOG_MAX_BYTES")
    log_backup_count: int = Field(alias="LOG_BACKUP_COUNT")
    log_total_size_cap: int = Field(alias="LOG_TOTAL_SIZE_CAP")
    log_file_path: str = Field(alias="LOG_PATH")
    json_mdc_mapping: dict[str, str] = Field(
        default={"rqUid": "request_id", "communicationId": "call_id"},
        alias="JSON_MDC_MAPPING",
    )
    context_vars: list[str] = Field(
        default=["request_id", "call_id", "manager_id"],
        alias="CONTEXT_VARS",
    )
    log_llm_responses: bool = True

    # Prometheus
    management_port: int = Field(alias="MANAGEMENT_PORT")
    prometheus_path: str = Field(alias="PROMETHEUS_PATH")

    # Audit
    audit_bootstrap_servers: str = Field(alias="AUDIT_BOOTSTRAP_SERVERS")
    audit_metamodel_topic: str = Field(alias="AUDIT_METAMODEL_TOPIC")
    audit_hints_topic: str = Field(alias="AUDIT_EVENT_TOPIC")

    # Postgres
    db_user: str = Field(alias="DB_USER")
    db_password: str = Field(alias="DB_PASS")
    db_name: str = Field(alias="DB_NAME")
    postgres_hosts: str = Field(alias="POSTGRES_HOSTS")
    postgres_pool_size: int = Field(alias="POSTGRES_POOL_SIZE")
    postgres_max_overflow: int = Field(alias="POSTGRES_MAX_OVERFLOW")
    postgres_pool_recycle_seconds: int = Field(alias="POSTGRES_POOL_RECYCLE_SECONDS")
    database_auto_create_schema: bool = Field(alias="DB_AUTO_CREATE_SCHEMA")

    gigachat_base_url: str = Field(alias="GIGACHAT_BASE_URL")
    gigachat_scope: str = Field(alias="GIGACHAT_SCOPE")
    gigachat_model: str = Field(alias="GIGACHAT_MODEL")
    gigachat_verify_ssl: bool = Field(alias="GIGACHAT_VERIFY_SSL")
    gigachat_cert_file: str | None = Field(alias="GIGACHAT_CERT_FILE")
    gigachat_key_file: str | None = Field(alias="GIGACHAT_KEY_FILE")
    gigachat_timeout_seconds: float = Field(alias="GIGACHAT_TIMEOUT_SECONDS")
    gigachat_max_concurrency: int = Field(alias="GIGACHAT_MAX_CONCURRENCY")
    gigachat_max_attempts: int = Field(alias="GIGACHAT_MAX_ATTEMPTS")
    gigachat_retry_base_seconds: float = Field(alias="GIGACHAT_RETRY_BASE_SECONDS")
    gigachat_validation_max_attempts: int = Field(
        default=3,
        alias="GIGACHAT_VALIDATION_MAX_ATTEMPTS",
        ge=1,
    )
    gigachat_validation_retry_seconds: float = Field(
        default=1,
        alias="GIGACHAT_VALIDATION_RETRY_SECONDS",
        ge=0,
    )
    gigachat_temperature: float | None = Field(alias="GIGACHAT_TEMPERATURE")

    efs_vip_km_manager_ids: Annotated[set[str], NoDecode] = Field(alias='EFS_VIP_KM_MANAGER_IDS')
    efs_vip_akm_manager_ids: Annotated[set[str], NoDecode] = Field(alias='EFS_VIP_AKM_MANAGER_IDS')
    efs_vip_dsb_manager_ids: Annotated[set[str], NoDecode] = Field(alias='EFS_VIP_DSB_MANAGER_IDS')
    efs_vip_tfs_manager_ids: Annotated[set[str], NoDecode] = Field(alias='EFS_VIP_TFS_MANAGER_IDS')

    active_criteria_codes: Annotated[set[str], NoDecode] = Field(alias="ACTIVE_CRITERIA_CODES")
    analyzed_manager_ids: Annotated[set[str], NoDecode] = Field(alias="ANALYZED_MANAGER_IDS")
    prompt_analyzer_manager_ids: Annotated[set[str], NoDecode] = Field(alias="PROMPT_ANALYZER_MANAGER_IDS")
    audio_analyzer_manager_ids: Annotated[set[str], NoDecode] = Field(alias="AUDIO_ANALYZER_MANAGER_IDS")
    factor_analyzer_manager_ids: Annotated[set[str], NoDecode] = Field(alias="FAQ_ANALYZER_MANAGER_IDS")
    audio_analyzer_url: str | None = Field(alias="AUDIO_ANALYZER_URL")
    factor_analyzer_url: str | None = Field(alias="FAQ_ANALYZER_URL")

    external_analyzer_timeout_seconds: float = Field(alias="EXTERNAL_ANALYZER_TIMEOUT_SECONDS")
    worker_poll_interval_seconds: float = Field(alias="WORKER_POLL_INTERVAL_SECONDS")
    worker_claim_limit: int = Field(alias="WORKER_CLAIM_LIMIT")
    worker_stale_task_seconds: int = Field(alias="WORKER_STALE_TASK_SECONDS")
    worker_recovery_interval_seconds: int = Field(
        alias="WORKER_RECOVERY_INTERVAL_SECONDS"
    )
    dialog_pipeline_concurrency: int = Field(alias="DIALOG_PIPELINE_CONCURRENCY")
    min_dialog_duration_seconds: int = Field(alias="MIN_DIALOG_DURATION_SECONDS")
    deposit_analysis_enabled: bool = Field(alias="DEPOSIT_ANALYSIS_ENABLED")
    criteria_version: str = Field(alias="CRITERIA_VERSION")
    prompt_version: str = Field(alias="PROMPT_VERSION")
    data_ttl_days: int = Field(alias="DATA_TTL_DAYS")
    calendar_filter_enabled: bool = Field(alias="CALENDAR_FILTER_ENABLED")

    dashboard_manager_batch_size: int = Field(alias='DASHBOARD_MANAGER_BATCH_SIZE')
    dashboard_cleanup_batch_size: int = Field(alias='DASHBOARD_CLEANUP_BATCH_SIZE')
    data_cleanup_interval_minutes: int = Field(
        default=60,
        alias="DATA_CLEANUP_INTERVAL_MINUTES",
        ge=1,
    )
    dashboard_enabled: bool = Field(alias="DASHBOARD_ENABLED")
    dashboard_cron_hour_utc: int = Field(alias="DASHBOARD_CRON_HOUR_UTC")
    dashboard_analysis_grace_seconds: int = Field(
        default=1800,
        alias="DASHBOARD_ANALYSIS_GRACE_SECONDS",
        ge=0,
    )
    metric_history_days: int = Field(alias="METRIC_HISTORY_DAYS")
    risk_rolling_window_days: int = Field(alias="RISK_ROLLING_WINDOW_DAYS")
    strengths_improvements_period_days: int = Field(
        alias="STRENGTHS_IMPROVEMENTS_PERIOD_DAYS"
    )
    strength_min_percent: float = Field(alias="STRENGTH_MIN_PERCENT")
    strengths_min_sample_size: int = Field(default=10, alias="STRENGTHS_MIN_SAMPLE_SIZE")
    strengths_sample_window_days: int = Field(default=30, alias="STRENGTHS_SAMPLE_WINDOW_DAYS")
    strengths_excluded_metric_codes: Annotated[set[str], NoDecode] = Field(default_factory=set, alias="STRENGTHS_EXCLUDED_METRIC_CODES")
    ui_hidden_metric_codes: Annotated[set[str], NoDecode] = Field(
        default_factory=set,
        alias="UI_HIDDEN_METRIC_CODES",
    )
    strengths_limit: int = Field(alias="STRENGTHS_LIMIT")
    dialog_strengths_limit: int = Field(alias="DIALOG_STRENGTHS_LIMIT")
    improvements_limit: int = Field(alias="IMPROVEMENTS_LIMIT")
    dialog_improvements_limit: int = Field(default=5, alias="DIALOG_IMPROVEMENTS_LIMIT")
    latest_communications_limit: int = Field(alias="LATEST_COMMUNICATIONS_LIMIT")
    communications_max_limit: int = Field(alias='COMMUNICATIONS_MAX_LIMIT')
    certain_improvement_communications_limit: int = Field(
        alias="CERTAIN_IMPROVEMENT_COMMUNICATIONS_LIMIT"
    )
    certain_improvement_periods_limit: int = Field(
        alias="CERTAIN_IMPROVEMENT_PERIODS_LIMIT"
    )
    critical_score_cap: int = Field(alias="CRITICAL_SCORE_CAP")
    empty_score_value: int = Field(alias="EMPTY_SCORE_VALUE")
    test_data_api_enabled: bool = Field(alias="TEST_DATA_API_ENABLED")

    @property
    def postgres_dsn(self) -> str:
        hosts = []
        for raw_host in self.postgres_hosts.split(","):
            host = raw_host.strip()
            if host:
                hosts.append(host)
        if not hosts:
            raise ValueError("POSTGRES_HOSTS должен содержать хотя бы один адрес")

        encoded_hosts = []
        for host in hosts:
            encoded_hosts.append(f"host={quote_plus(host)}")
        host_query = "&".join(encoded_hosts)
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
        return self.gigachat_model

    @field_validator(
        "analyzed_manager_ids",
        "prompt_analyzer_manager_ids",
        "audio_analyzer_manager_ids",
        "factor_analyzer_manager_ids",
        "efs_vip_km_manager_ids",
        "efs_vip_akm_manager_ids",
        "efs_vip_dsb_manager_ids",
        "efs_vip_tfs_manager_ids",
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
            result = set()
            for item in items:
                manager_id = str(item).strip()
                if manager_id:
                    result.add(manager_id.zfill(8))
            return result
        return value

    @field_validator(
        "active_criteria_codes",
        "strengths_excluded_metric_codes",
        "ui_hidden_metric_codes",
        mode="before",
    )
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
            result = set()
            for item in items:
                code = str(item).strip()
                if code:
                    result.add(code)
            return result
        return value

    @model_validator(mode="after")
    def validate_sampling_parameters(self) -> "Settings":
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

        role_sets = {
            "EFS_VIP_KM": self.efs_vip_km_manager_ids,
            "EFS_VIP_AKM": self.efs_vip_akm_manager_ids,
            "EFS_VIP_DSB": self.efs_vip_dsb_manager_ids,
            "EFS_VIP_TFS": self.efs_vip_tfs_manager_ids,
        }
        seen: dict[str, str] = {}
        for role, manager_ids in role_sets.items():
            for manager_id in manager_ids:
                previous_role = seen.get(manager_id)
                if previous_role:
                    raise ValueError(f"Manager {manager_id} in role {previous_role} and {role}")
                seen[manager_id] = role
        missing_roles = self.analyzed_manager_ids - set(seen)
        if missing_roles:
            raise ValueError(f"every analyzing manager should have role: {missing_roles}")

        return self

    def static_manager_roles(self) -> dict[str, str]:
        role_sets = {
            "EFS_VIP_KM": self.efs_vip_km_manager_ids,
            "EFS_VIP_AKM": self.efs_vip_akm_manager_ids,
            "EFS_VIP_DSB": self.efs_vip_dsb_manager_ids,
            "EFS_VIP_TFS": self.efs_vip_tfs_manager_ids,
        }
        result = {}
        for role, manager_ids in role_sets.items():
            for manager_id in manager_ids:
                result[manager_id] = role
        return result


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
