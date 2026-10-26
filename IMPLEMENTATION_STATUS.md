# Статус реализации Analyzer — dashboard v2

## Реализовано в текущем рефакторинге

- два последовательных LLM-запроса на звонок: общие правила и вклады;
- технический критерий `DEPOSIT_TOPIC` и полное исключение блока вкладов при
  отсутствии темы;
- строгий ответ LLM `code`, `score`, `quote`;
- детерминированный расчёт штрафов, critical cap и fraud;
- отсеивание звонков короче 50 секунд до INSERT;
- нормализованная таблица `dialog_metric_results`;
- готовая карточка звонка в `dialogs.dialog_report`;
- готовые snapshots основной страницы, клиентов и метрик;
- квартальный личный score и командная медиана;
- скользящие 30-дневные показатели и дневная дельта;
- четыре недельные точки для popup метрики;
- ровно восемь публичных GET;
- ручная и плановая сборка dashboard snapshot;
- все лимиты, окна и feature flags вынесены в ENV;
- Alembic `analyzer_0003` успешно применён к локальному PostgreSQL;
- Analyzer image успешно собран;
- OpenAPI проверен: восемь маршрутов присутствуют;
- синхронные unit-тесты новой логики: 12 успешных.

## Ещё требуется интеграционная проверка

- полный E2E двух звонков через локальную Ollama после перезапуска всего Compose;
- нагрузочный тест новых GET на заполненной витрине;
- согласование окончательного полного набора Prompt 4Q критериев с аналитиком.

<!-- LEGACY_STATUS_START

## Реализовано

- независимые проекты Kafka Producer, Kafka Consumer, Data Cleaner, Analyzer,
  UCP Mock и PostgreSQL;
- отдельные Dockerfile, Python dependencies и Alembic history для каждого Python-сервиса;
- схемы PostgreSQL `kafka`, `cleaner`, `analyzer` без чтения чужих таблиц;
- ProtoBuf mapper, роли обоих направлений звонка, эмоции, speaker metadata, тайм-коды и word alignments;
- дедупликация и сборка последовательных частей диалога;
- настраиваемое AES-GCM шифрование чанков и полного Cleaner payload;
- Data Cleaner с bounded callback queue, UCP enrichment и best-effort delivery;
- календарная фильтрация Analyzer;
- 27 Prompt 4Q критериев из Word-таблицы;
- строгий контракт GigaChat, точная цитата при нарушении, Q-Score и critical cap;
- общий semaphore, пять попыток и token-aware atomic batching;
- результат анализа звонка хранится вместе с диалогом, а daily, weekly, four-week и quarterly разнесены по отдельным таблицам;
- конфигурируемые множества менеджеров для Prompt, Audio и FAQ-анализаторов;
- явные оркестраторы анализа звонка и четырёх уровней агрегированных отчётов;
- взвешенный Q-Score и агрегаты каждого критерия на всех уровнях;
- completed-only GET, ручные idempotent run endpoints и schedulers;
- recovery `processing -> waiting`, безопасные error codes и Prometheus metrics;
- полный локальный Docker Compose без Kubernetes: Kafka, Producer, UCP Mock, Ollama, PostgreSQL и три основных сервиса;
- единая чистая структура `api -> services -> database/repositories` во всех сервисах;
- отдельные Pydantic-схемы и доменные исключения без SQL-запросов в API и services;
- слой `agents` в Analyzer: prompt loader, prompt/report agents, GigaChat и локальный Ollama provider;
- все тексты промптов вынесены в MD/YAML и валидируются один раз при старте;
- структурированный ответ GigaChat через строгую Pydantic JSON Schema;
- настройки LLM и multihost PostgreSQL полностью управляются через ENV;
- Swagger Kafka Producer, самостоятельно разбивающий цельный диалог на ProtoBuf-чанки;
- переключаемый набор активных критериев для лёгкого локального E2E.

## Проверено локально

- сборка всех шести собственных Docker images;
- три независимые Alembic migration chain на реальном PostgreSQL;
- создание 13 таблиц в трёх схемах;
- readiness Analyzer и Data Cleaner;
- незавершённый публичный отчёт `404` и Cleaner callback `202`;
- 37 unit-тестов календаря, профилей менеджеров, оркестрации, Q-Score,
  критериев, prompt loader, batching, периодов, ProtoBuf mapping, assembler,
  Cleaner contracts, masking и тестового Producer;
- Ruff lint для всех четырёх основных Python-проектов;
- реальный E2E через Docker: цельный HTTP-диалог разбит на четыре ProtoBuf-чанка,
  прошёл Kafka, Consumer, Cleaner, UCP Mock, Analyzer и Ollama; публичный GET
  вернул `completed`, `qScore=100` и три структурированных результата;
- после E2E промежуточные строки Kafka/Cleaner удалены, а Analyzer сохранил один
  диалог и четыре реплики;
- k6 smoke: 20 VU, 8 888 HTTP-запросов за 10 секунд, 0% ошибок, p95 117,68 мс, p99 144,63 мс.

## Для интеграционного стенда

Для локального E2E внешние Kafka, UCP и платная LLM не нужны. Для интеграции с корпоративным стендом всё ещё потребуются реальные адреса и секреты. Audio и FAQ/IDP не входят в реализованный MVP и не маскируются ложным статусом `completed`.

LEGACY_STATUS_END -->
