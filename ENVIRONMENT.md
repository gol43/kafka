# ENV Analyzer

## Где находятся настройки

| Файл | Где используется | Назначение |
|---|---|---|
| `.env.example` | корневые `docker-compose.yml` и `docker-compose.analyzer.yml` | Полный пример локальной конфигурации всего стенда |
| `analyzer/.env.example` | отдельный запуск Analyzer | Короткий пример только для Analyzer |
| `.env` | Docker Compose и `pydantic-settings` | Реальные локальные значения; файл не должен попадать в Git |
| `analyzer/app/config.py` | весь Analyzer | Типы, значения по умолчанию и проверки ENV |

## Подключение и роли менеджеров

| ENV | Где используется | Для чего нужен |
|---|---|---|
| `DB_USER`, `DB_PASS`, `DB_NAME` | `database/connection.py` через `Settings` | Учётные данные PostgreSQL |
| `POSTGRES_HOSTS` | `database/connection.py` | Список `host:port` через запятую; выбирается writable primary |
| `POSTGRES_DSN` | `database/connection.py` | Необязательный готовый DSN вместо отдельных DB-полей |
| `POSTGRES_POOL_SIZE`, `POSTGRES_MAX_OVERFLOW` | `database/connection.py` | Ограничения пула соединений |
| `POSTGRES_POOL_RECYCLE_SECONDS` | `database/connection.py` | Период обновления соединений пула |
| `EFS_VIP_KM_MANAGER_IDS` | `config.py`, `dashboard_builder.py` | Менеджеры роли EFS_VIP_KM |
| `EFS_AKM_VIP_MANAGER_IDS` | там же | Менеджеры роли EFS_AKM_VIP |
| `EFS_VIP_DSB_MANAGER_IDS` | там же | Менеджеры роли EFS_VIP_DSB |
| `EFS_VIP_TFS_MANAGER_IDS` | там же | Менеджеры роли EFS_VIP_TFS |

Один табельный номер разрешён только в одной роли. Каждый менеджер из
`ANALYZED_MANAGER_IDS` обязан находиться в одном role-list.

## Приём и анализ диалогов

| ENV | Где используется | Для чего нужен |
|---|---|---|
| `ANALYZED_MANAGER_IDS` | `dialog_intake.py` | Белый список анализируемых менеджеров |
| `PROMPT_ANALYZER_MANAGER_IDS` | `config.py` | Менеджеры с обязательными hygiene/deposit/risk запросами |
| `AUDIO_ANALYZER_MANAGER_IDS`, `FACTOR_ANALYZER_MANAGER_IDS` | `config.py` | Включение будущих внешних анализаторов |
| `AUDIO_ANALYZER_URL`, `FACTOR_ANALYZER_URL` | `main.py` | HTTP-адреса внешних анализаторов |
| `MIN_DIALOG_DURATION_SECONDS` | `dialog_intake.py` | Отбрасывает короткие звонки до записи в БД |
| `CALENDAR_FILTER_ENABLED` | `dialog_intake.py` | Включает правила рабочих дней и cutoff |
| `WORKER_POLL_INTERVAL_SECONDS` | `analysis_worker.py` | Пауза между чтениями очереди |
| `WORKER_CLAIM_LIMIT` | `analysis_worker.py` | Максимальный размер одного claim |
| `DIALOG_PIPELINE_CONCURRENCY` | `analysis_worker.py` | Лимит одновременно обрабатываемых диалогов |
| `DATA_TTL_DAYS` | repositories | TTL диалогов, ошибок, reports, aggregates и snapshots |
| `DEPOSIT_ANALYSIS_ENABLED` | `prompt_dialog_analyzer.py` | Быстрое выключение блока вкладов |

## LLM

| ENV | Где используется | Для чего нужен |
|---|---|---|
| `LLM_PROVIDER` | `gigachat_provider/factory.py` | Выбор `gigachat` или `ollama` |
| `GIGACHAT_CREDENTIALS`, `GIGACHAT_SCOPE` | GigaChat provider | Авторизация GigaChat |
| `GIGACHAT_MODEL`, `OLLAMA_MODEL` | LLM providers | Название модели |
| `GIGACHAT_MAX_CONCURRENCY` | GigaChat provider | Общий семафор запросов к GigaChat |
| `GIGACHAT_MAX_ATTEMPTS` | GigaChat provider | Максимум повторов LLM-запроса |
| `GIGACHAT_TIMEOUT_SECONDS` | GigaChat provider | Таймаут запроса |
| `GIGACHAT_TEMPERATURE`, `GIGACHAT_TOP_P` | GigaChat provider | Управление вариативностью; одновременно задаётся только одно |
| `GIGACHAT_MAX_INPUT_TOKENS` | prompt analyzer | Верхняя граница входного контекста |
| `GIGACHAT_MAX_OUTPUT_TOKENS` | LLM providers | Максимум токенов ответа |
| `ACTIVE_CRITERIA_CODES` | `prompt_loader.py` | Необязательное ограничение активных YAML-критериев |
| `LOG_LLM_RESPONSES` | agents | Вывод полного ответа LLM в debug-лог |

## Витрина

| ENV | Где используется | Для чего нужен |
|---|---|---|
| `DASHBOARD_ENABLED` | `dashboard_scheduler.py` | Включает cron-сборку |
| `DASHBOARD_CRON_HOUR_UTC` | scheduler и worker | Cutoff рабочего дня, по умолчанию 18 UTC |
| `DASHBOARD_WAIT_INTERVAL_SECONDS` | scheduler | Интервал проверки начатых до cutoff задач |
| `DASHBOARD_MANAGER_BATCH_SIZE` | `dashboard_builder.py` | Число менеджеров в одном DB/memory batch |
| `DASHBOARD_CLEANUP_BATCH_SIZE` | `dashboard_repository.py` | Размер пакетного TTL-удаления |
| `METRIC_ROLLING_WINDOW_DAYS` | builder | Окно strengths/improvements, по умолчанию 30 дней |
| `RISK_ROLLING_WINDOW_DAYS` | builder | Окно клиентских рисков, по умолчанию 10 дней |
| `STRENGTH_MIN_PERCENT` | builder | Граница strengths/improvements, по умолчанию 80% |
| `STRENGTHS_LIMIT`, `IMPROVEMENTS_LIMIT` | builder | Размер top-блоков |
| `METRIC_WEEKLY_POINTS_LIMIT` | builder | Число завершённых недель в popup метрики |
| `LATEST_COMMUNICATIONS_LIMIT` | builder | Число последних звонков в snapshot |
| `COMMUNICATIONS_MAX_LIMIT` | manager API | Максимальный `limit` списка коммуникаций |
| `EMPTY_SCORE_VALUE` | builder | Значение Q-score при отсутствии истории |
| `TEST_DATA_API_ENABLED` | `main.py` | Включает тестовую ручку генерации истории |
