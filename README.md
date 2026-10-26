# Communication Quality Platform

Актуальная документация Analyzer после перехода на восемь готовых витрин.
Kafka Consumer, Data Cleaner и тестовый Producer продолжают работать как
транспортный контур, но в этом документе подробно разобран именно Analyzer.

## 1. Главный принцип

Analyzer один раз анализирует каждый принятый звонок, сохраняет нормализованные
результаты критериев и заранее формирует данные для фронтенда. Публичные GET не
вызывают LLM и не выполняют тяжёлые группировки.

```text
Data Cleaner callback
        ↓
первичное отсеивание
        ↓
dialogs + analysis_tasks
        ↓
два запроса LLM
        ↓
Python рассчитывает score
        ↓
dialogs + dialog_metric_results
        ↓
ежедневный DashboardBuilder
        ↓
готовые snapshots
        ↓
8 простых GET
```

## 2. Чистая архитектура

| Слой | Что делает | Чего не делает |
|---|---|---|
| `api` | Принимает HTTP, валидирует параметры, преобразует ошибки в HTTP-коды | Не выполняет SQL и расчёты |
| `services` | Отсеивание, orchestration, score, ранжирование и сборка витрин | Не содержит SQL |
| `database/repositories` | Только читает и записывает PostgreSQL | Не принимает бизнес-решения |
| `agents` | Загружает prompt-ресурсы и вызывает LLM | Не считает score и не пишет в БД |
| `schemas` | Pydantic-контракты HTTP, LLM и доменных объектов | Не содержит workflow |

Точка сборки зависимостей — [`analyzer/app/main.py`](analyzer/app/main.py).

## 3. Конфигурация

Все изменяемые ограничения читаются из ENV в
[`analyzer/app/config.py`](analyzer/app/config.py):

```env
ANALYZED_MANAGER_IDS=00000001,00000002
MIN_DIALOG_DURATION_SECONDS=50
DEPOSIT_ANALYSIS_ENABLED=true

DIALOG_PIPELINE_CONCURRENCY=10
GIGACHAT_MAX_CONCURRENCY=1
GIGACHAT_MAX_ATTEMPTS=5

DASHBOARD_ENABLED=true
DASHBOARD_CRON_HOUR_UTC=18
METRIC_ROLLING_WINDOW_DAYS=30
STRENGTH_MIN_PERCENT=80

STRENGTHS_LIMIT=3
IMPROVEMENTS_LIMIT=3
RISK_CLIENTS_LIMIT=4
LATEST_COMMUNICATIONS_LIMIT=5
METRIC_FAILED_COMMUNICATIONS_LIMIT=3
METRIC_WEEKLY_POINTS_LIMIT=4
```

`DIALOG_PIPELINE_CONCURRENCY` ограничивает количество одновременно работающих
pipeline звонков. `GIGACHAT_MAX_CONCURRENCY` ограничивает именно HTTP-запросы
к общей LLM. Поэтому несколько pipeline могут ждать один общий LLM semaphore.

## 4. Данные callback

Контракт описан в
[`analyzer/app/schemas/dialogs.py`](analyzer/app/schemas/dialogs.py).
Analyzer ожидает, что предыдущий контур уже передал необходимые данные:

```json
{
  "call_id": "call-deposit-001",
  "manager_id": "00000001",
  "manager_name": "Анна Петрова",
  "client_epk": "epk-10001",
  "client_fio": "Иванов Иван Иванович",
  "occurred_at": "2026-10-26T09:30:00Z",
  "channel": "phone",
  "duration_seconds": 180,
  "cleaned_text": "Сотрудник: Добрый день...",
  "participants": [],
  "utterances": []
}
```

Если `client_fio` не передан отдельно, репозиторий пытается взять имя участника
с ролью `client`.

## 5. Первичное отсеивание

Callback вызывает
[`DialogIntakeService.accept()`](analyzer/app/services/dialog_intake.py).

Проверки выполняются до INSERT:

1. Длительность должна быть не меньше `MIN_DIALOG_DURATION_SECONDS`.
2. Время должно пройти правила
   [`calendar_policy.py`](analyzer/app/services/calendar_policy.py).
3. `manager_id` должен находиться в `ANALYZED_MANAGER_IDS`.
4. Менеджеру должен быть назначен Prompt Analyzer.

Отсеянный звонок получает HTTP `202`, но не появляется в `analyzer.dialogs` и
не создаёт `analysis_tasks`. Для остальной системы такого звонка не существует.

Принятый звонок сохраняется через
[`DialogRepository.save_cleaned_dialog()`](analyzer/app/database/repositories/dialog_repository.py),
затем `AnalysisWorker.enqueue()` создаёт персистентное задание.

## 6. Worker и ошибки

[`AnalysisWorker`](analyzer/app/services/analysis_worker.py) выполняет простой
цикл:

```text
recover processing → waiting
claim waiting через FOR UPDATE SKIP LOCKED
войти в pipeline semaphore
вызвать DialogAnalysisOrchestrator
completed либо failed
```

При падении процесса незавершённые задания возвращаются в `waiting`. После
последней неуспешной попытки LLM:

- `analysis_tasks.status = failed`;
- `dialogs.analysis_status = failed`;
- публичные GET возвращают `404`;
- worker продолжает следующий звонок.

## 7. Два LLM-запроса

Единственная точка Prompt-анализа —
[`PromptDialogAnalyzer`](analyzer/app/services/prompt_dialog_analyzer.py).

Для каждого принятого звонка при включённом вкладовом анализе выполняются ровно
два последовательных запроса:

```text
1. block=general — общие правила коммуникации.
2. block=deposit — критерии вкладов и DEPOSIT_TOPIC.
```

[`PromptLoader`](analyzer/app/agents/prompt_loader.py) загружает при старте:

- [`dialog_system.md`](analyzer/app/agents/prompts/dialog_system.md);
- [`dialog_user.md`](analyzer/app/agents/prompts/dialog_user.md);
- общие YAML-критерии;
- [`deposits.yaml`](analyzer/app/agents/prompts/criteria/deposits.yaml);
- [`metric_metadata.yaml`](analyzer/app/agents/prompts/metric_metadata.yaml);
- [`positive_templates.yaml`](analyzer/app/agents/prompts/positive_templates.yaml).

LLM возвращает только:

```json
{"code": "GENERAL_01", "score": 0, "quote": "точная цитата"}
```

Штрафы, критичность и рекомендации не передаются модели как право принимать
решение. Их источник — YAML.

## 8. Ветка вкладов

`DEPOSIT_TOPIC` является техническим gate-критерием второго ответа.

Если `DEPOSIT_TOPIC = 0`:

- Python принудительно ставит всем вкладовым критериям `score=0`;
- сохраняет `deposit_topic=false`;
- ставит `included_in_analytics=false`;
- не включает вкладовый блок в итоговый score;
- не показывает его во фронтовых блоках.

Если `DEPOSIT_TOPIC = 1`, вкладовые критерии участвуют в score и витринах.

## 9. Расчёт оценки звонка

Код находится в [`scoring.py`](analyzer/app/services/scoring.py).

```text
general_score = max(0, 100 − штрафы общих нарушений)
deposit_score = max(0, 100 − штрафы вкладовых нарушений)

без темы вкладов:
    final_score = general_score

с темой вкладов:
    final_score = (general_score + deposit_score) / 2
```

Критичное нарушение вычитает штраф и ограничивает итог сверху значением
`CRITICAL_SCORE_CAP`. Fraud со штрафом 100 обнуляет вкладовый блок, но не общий.

## 10. Хранение результата звонка

Модели находятся в [`database/models.py`](analyzer/app/database/models.py).
Миграция —
[`0003_dashboard_read_models.py`](analyzer/alembic/versions/0003_dashboard_read_models.py).

`analyzer.dialogs` содержит звонок и готовую карточку `dialog_report`.

`analyzer.dialog_metric_results` содержит одну строку на критерий:

```text
call_id, manager_id, client_epk
metric_code, metric_title, metric_block
score, severity, penalty
quote, recommendation
included_in_analytics, occurred_at
```

Вкладовые строки при отсутствии темы сохраняются для диагностики, но имеют
`included_in_analytics=false`.

## 11. Готовая карточка коммуникации

[`build_dialog_report()`](analyzer/app/services/dialog_report_builder.py)
формирует карточку до установки `completed`:

- ФИО клиента;
- дата и время;
- итоговая оценка;
- количество отклонений;
- топ-3 выполненных метрики;
- стабильная положительная фраза;
- топ-3 нарушенных метрики;
- рекомендации и цитаты.

Шаблон выбирается по hash `call_id`, поэтому повторный GET возвращает тот же
текст.

## 12. Ежедневные витрины

[`DashboardScheduler`](analyzer/app/services/dashboard_scheduler.py) ежедневно
запускает [`DashboardBuilder`](analyzer/app/services/dashboard_builder.py) для
предыдущего завершённого дня.

Builder последовательно рассчитывает:

1. Личный средний score с начала квартала.
2. Медиану личных результатов всех менеджеров из ENV.
3. Три календарных месяца квартала.
4. Скользящие 30 дней по каждой метрике.
5. Значение того же окна на вчерашнем snapshot.
6. Топ-3 сильные стороны с границей 80%.
7. Топ-3 зоны развития ниже 80%.
8. Топ-4 уникальных клиента с нарушениями.
9. Четыре завершённые календарные недели метрики.
10. Пять последних completed-коммуникаций.

Результаты записываются через
[`DashboardRepository`](analyzer/app/database/repositories/dashboard_repository.py)
в готовые JSONB snapshots. GET только выбирает последнюю строку.

## 13. Восемь публичных GET

Маршруты находятся в [`api/manager.py`](analyzer/app/api/manager.py), ответы
собирает [`ManagerService`](analyzer/app/services/manager_service.py).

```text
1. GET /manager/{manager_id}/q-score
2. GET /manager/{manager_id}/clients-at-risk
3. GET /manager/{manager_id}/strengths
4. GET /manager/{manager_id}/improvements
5. GET /manager/{manager_id}/communications
6. GET /manager/{manager_id}/clients/{client_epk}/metrics/{metric_code}
7. GET /manager/{manager_id}/metrics/{metric_code}
8. GET /manager/dialogs/{call_id}
```

Ручной пересчёт витрин:

```http
POST /analysis/run/dashboard?date=2026-10-25
```

## 14. E2E-пример A: разговор про вклад

Исходные данные:

```text
call_id: call-deposit-001
manager_id: 00000001
client: Иванов Иван Иванович
duration: 180 секунд
text: менеджер приветствует клиента, обсуждает ставку и Особый Плюс
```

Трасса:

```text
callbacks.cleaned_dialog()
→ DialogIntakeService.accept()
  → 180 >= 50
  → календарь разрешает звонок
  → 00000001 присутствует в set
→ DialogRepository.save_cleaned_dialog()
→ AnalysisWorker.enqueue()
→ AnalysisWorker.claim()
→ DialogAnalysisOrchestrator.process()
→ PromptDialogAnalyzer.analyze()
  → PromptAnalysisAgent.analyze(block="general")
  → PromptAnalysisAgent.analyze(block="deposit")
  → DEPOSIT_TOPIC=1
  → calculate_dialog_score()
→ build_dialog_report()
→ DialogRepository.complete_analysis()
  → UPDATE dialogs
  → INSERT dialog_metric_results
→ task completed
```

Если `general_score=90`, `deposit_score=70` и есть критичное нарушение:

```text
(90 + 70) / 2 = 80
critical cap = 80
final_score = 80
```

## 15. E2E-пример B: разговор не про вклад

```text
call_id: call-card-002
manager_id: 00000001
client: Петров Пётр Петрович
duration: 95 секунд
text: клиент спрашивает о перевыпуске карты
```

До LLM путь совпадает с первым примером. Далее:

```text
general request → результаты общих критериев
deposit request → DEPOSIT_TOPIC=0
Python:
  все deposit score принудительно 0
  deposit_topic=false
  included_in_analytics=false
  deposit_score=null
  final_score=general_score
```

Вкладовые нули видны только внутри БД для диагностики. Они отсутствуют в
Q-Score, сильных сторонах, зонах развития, клиентских нарушениях и карточке
звонка.

## 16. Пограничные сценарии

### Диалог короче 50 секунд

`DialogIntakeService` возвращает `duration_filtered`. INSERT и LLM-вызовов нет.

### Менеджер выключен

Возвращается `manager_filtered`. Строк в БД нет.

### Ошибка первого LLM-запроса

Второй запрос не запускается. После исчерпания retry звонок получает `failed`.

### Ошибка второго LLM-запроса

Частичный общий результат наружу не выходит. Весь звонок получает `failed`.

### Падение процесса

При следующем старте `recover_processing()` возвращает task в `waiting`.

### Витрина ещё не построена

GET блока отвечает `404`, а не рассчитывает данные синхронно.

## 17. Проверка локально

```bash
docker compose build analyzer
docker compose up -d postgres
docker compose run --rm --no-deps analyzer alembic upgrade head
docker compose up -d analyzer
```

Swagger Analyzer:

```text
http://localhost:8082/docs
```

Ручная сборка витрин:

```bash
curl -X POST "http://localhost:8082/analysis/run/dashboard?date=2026-10-25"
```

## 18. Что намеренно не делает текущая версия

- Не вызывает LLM при GET.
- Не строит старую цепочку daily/weekly/four-week/quarterly.
- Не показывает waiting, processing и failed.
- Не сохраняет отсеянные звонки.
- Не считает вкладовые критерии нарушениями при отсутствии темы.
- Не реализует Audio и FAQ/IDP внутри Analyzer.

---

<!-- LEGACY_DOCUMENTATION_START

Система принимает чанки расшифровки звонка, собирает и обезличивает диалог,
анализирует его и последовательно строит дневной, недельный, four-week и
квартальный отчёты. Для ручной проверки в репозитории также находятся Kafka
Producer со Swagger, mock UCP и полностью локальная бесплатная LLM. Сервисы не
импортируют код друг друга и не читают чужие схемы БД.

## 1. Состав проекта

| Проект | Ответственность | Схема PostgreSQL |
|---|---|---|
| [`kafka-consumer`](kafka-consumer/) | Читает ProtoBuf, хранит чанки до `is_last`, собирает диалог и передаёт его в Cleaner | `kafka` |
| [`data-cleaner`](data-cleaner/) | Расшифровывает payload, обезличивает текст, получает обязательные данные UCP и вызывает подписчиков | `cleaner` |
| [`analyzer`](analyzer/) | Отбирает менеджеров, выполняет анализы и предоставляет только завершённые отчёты | `analyzer` |
| [`kafka-producer`](kafka-producer/) | Принимает цельный тестовый диалог через Swagger, разбивает его на ProtoBuf-чанки и публикует в единственный topic | — |
| [`ucp-mock`](ucp-mock/) | Возвращает обязательный тестовый `client_epk`, чтобы Cleaner можно было пройти без корпоративного UCP | — |
| [`postgres`](postgres/) | Создаёт схемы для локального запуска | — |

У каждого Python-сервиса собственные `Dockerfile` и `pyproject.toml`. Три
сервиса, владеющие БД, дополнительно имеют собственные Alembic и таблицу
`alembic_version` в своей схеме.

## 2. Полный путь одного звонка

### Шаг 1. Получение Kafka-сообщения

Точка сборки Kafka Consumer находится в
[`kafka-consumer/app/main.py`](kafka-consumer/app/main.py). В lifespan создаются
репозиторий, CryptoService, HTTP-клиент Cleaner и `DialogConsumer`.

[`DialogConsumer`](kafka-consumer/app/services/consumer.py) выполняет следующий
цикл:

1. Читает сообщение из Kafka без auto-commit.
2. Десериализует `RecognitionResponse` из
   [`saluteSpeech.proto`](kafka-consumer/app/proto/saluteSpeech.proto).
3. [`proto_mapper.py`](kafka-consumer/app/services/proto_mapper.py) превращает
   ProtoBuf в Pydantic-модель чанка, сохраняя роли, тайм-коды, эмоции и word
   alignments.
4. Передаёт чанк в
   [`ChunkService.handle`](kafka-consumer/app/services/chunk_service.py).
5. После завершения обработки делает commit Kafka offset.

В памяти на этом шаге находится только текущее Kafka-сообщение и его Pydantic-
представление.

### Шаг 2. Хранение и сборка чанков

[`DialogChunkRepository`](kafka-consumer/app/database/repositories/dialog_chunk_repository.py)
сохраняет чанк в `kafka.dialog_chunks`. Уникальность `(call_id, part)` исключает
дубликаты. Состояние звонка хранится в `kafka.dialog_state`. Payload может
храниться зашифрованным — это задаёт `CHUNK_STORAGE_ENCRYPTED`.

Когда приходит `is_last=true`, репозиторий:

1. блокирует `dialog_state` через `FOR UPDATE`;
2. читает все чанки по `call_id`, сортируя по `part`;
3. удаляет чанки и состояние в той же транзакции;
4. возвращает чанки в память `ChunkService`.

[`assembler.py`](kafka-consumer/app/services/assembler.py) собирает цельный
`StructuredDialog`. Разрыва текста одного чанка или реплики не происходит.
[`CleanerClient`](kafka-consumer/app/services/cleaner_client.py) отправляет
диалог в Data Cleaner по HTTP. Полный payload отдельно шифруется настройкой
`CLEANER_REQUEST_ENCRYPTED`.

Контракт намеренно at-most-once: к моменту HTTP-запроса чанки уже удалены. Если
Cleaner не ответил `202`, звонок считается потерянным и не восстанавливается.

### Шаг 3. Приём Data Cleaner

HTTP-ручка находится в
[`data-cleaner/app/api/dialogs.py`](data-cleaner/app/api/dialogs.py). API только
валидирует контракт и вызывает
[`DialogService`](data-cleaner/app/services/dialog_service.py). Сервис проверяет
незашифрованный payload и записывает задание в `cleaner.cleaner_jobs` через
[`CleanerJobRepository`](data-cleaner/app/database/repositories/cleaner_job_repository.py).
Ответ `202` означает только то, что Data Cleaner принял ответственность за
диалог.

### Шаг 4. Очистка и UCP

[`CleanerWorker`](data-cleaner/app/services/worker.py) циклически выбирает
`waiting`-задания через `FOR UPDATE SKIP LOCKED`:

1. при необходимости расшифровывает payload;
2. валидирует клиента и сотрудника;
3. вызывает [`UcpClient`](data-cleaner/app/services/ucp_client.py);
4. обезличивает полный текст и каждую реплику через
   [`TextCleaner`](data-cleaner/app/services/text_cleaner.py);
5. кладёт готовый callback в ограниченную очередь
   [`CallbackDispatcher`](data-cleaner/app/services/dispatcher.py);
6. всегда удаляет `cleaner_jobs`, в том числе после ошибки.

В БД Cleaner временно лежит исходный payload. Очищенный объект живёт в памяти до
постановки в callback queue. Dispatcher асинхронно вызывает все URL из
`CLEANER_CALLBACK_URLS`; недоступность одного подписчика не блокирует остальных.

### Шаг 5. Допуск диалога в Analyzer

Cleaner вызывает
[`POST /internal/v1/dialogs/cleaned`](analyzer/app/api/callbacks.py). Ручка
передаёт объект в
[`DialogIntakeService`](analyzer/app/services/dialog_intake.py).

До записи в БД выполняются две проверки:

1. [`calendar_policy.py`](analyzer/app/services/calendar_policy.py) определяет
   рабочую дату. Суббота, воскресенье и пятница после 18:00 UTC отбрасываются;
   воскресенье после 18:00 UTC относится к понедельнику.
2. `Settings.analyzers_for(manager_id)` проверяет наличие менеджера в
   `ANALYZED_MANAGER_IDS` и формирует его обязательную цепочку из трёх set:
   `PROMPT_ANALYZER_MANAGER_IDS`, `AUDIO_ANALYZER_MANAGER_IDS` и
   `FAQ_ANALYZER_MANAGER_IDS`.

Если менеджера нет в `ANALYZED_MANAGER_IDS`, сервис возвращает `202`, но ничего
не сохраняет и анализ не запускает. Это намеренное удаление, а не отдельный
статус.

Пример ENV:

```env
ANALYZED_MANAGER_IDS=00000001,00000002,00000003
PROMPT_ANALYZER_MANAGER_IDS=00000001,00000002,00000003
AUDIO_ANALYZER_MANAGER_IDS=00000002
FAQ_ANALYZER_MANAGER_IDS=00000002,00000003
AUDIO_ANALYZER_URL=http://audio-analyzer:8080
FAQ_ANALYZER_URL=http://faq-analyzer:8080
```

В результате менеджер `00000001` получает только Prompt-анализ, `00000002` —
Prompt → Audio → FAQ, а `00000003` — Prompt → FAQ. Поиск выполняется в `set`,
то есть имеет среднюю сложность O(1).

### Шаг 6. Что такое AnalysisTask

После сохранения диалога `DialogIntakeService` создаёт задание типа `dialog` в
`analyzer.analysis_tasks` через
[`AnalysisTaskRepository`](analyzer/app/database/repositories/analysis_task_repository.py).

`AnalysisTask` — не бизнес-сущность и не отчёт. Это персистентное письмо для
worker, содержащее:

- тип работы: `dialog`, `daily`, `weekly`, `four_week`, `quarterly`;
- ключ сущности;
- manager ID;
- приоритет, статус и техническую ошибку;
- границы периода для агрегированного отчёта.

Очередь нужна, чтобы после падения pod задания `processing` вернулись в
`waiting`. Без неё диалог мог бы сохраниться, но анализ уже никогда бы не
запустился.

### Шаг 7. Общий semaphore и запуск задания

Бесконечный цикл расположен в
[`AnalysisWorker.run`](analyzer/app/services/analysis_worker.py). Worker забирает
не больше `WORKER_CLAIM_LIMIT` строк и запускает их через один
`asyncio.Semaphore(GIGACHAT_MAX_CONCURRENCY)`. Этот semaphore общий для звонков
и всех агрегированных отчётов.

У выбранного LLM-провайдера есть второй защитный semaphore с тем же лимитом
непосредственно вокруг HTTP-вызова модели. Worker ограничивает полные pipeline,
provider не позволяет случайно превысить лимит отдельным запросом.

### Шаг 8. Анализ одного диалога

[`DialogAnalysisOrchestrator`](analyzer/app/services/dialog_analysis_orchestrator.py)
— единственная точка оркестрации анализа звонка. Он читает
`Dialog.required_analyzers` и строго последовательно выполняет шаги. При ошибке
текущего анализатора дальнейшие не вызываются.

- Prompt: [`PromptDialogAnalyzer`](analyzer/app/services/prompt_dialog_analyzer.py)
  вызывает [`PromptAnalysisAgent`](analyzer/app/agents/prompt_analysis_agent.py),
  проверяет наличие всех активных критериев и рассчитывает Q-score кодом.
- Audio и FAQ: [`ExternalAnalyzerAgent`](analyzer/app/agents/external_analyzer_agent.py)
  асинхронно вызывает `POST /internal/v1/analyze` соответствующего сервиса.

PromptLoader находится в
[`analyzer/app/agents/prompt_loader.py`](analyzer/app/agents/prompt_loader.py).
При старте процесса он один раз загружает YAML-критерии и все MD-промпты.
`ACTIVE_CRITERIA_CODES` может оставить для локального теста только часть
каталога; пустое значение включает все критерии. Промпты не объявляются в
Python.

Только после успеха всей обязательной цепочки оркестратор одним обновлением
ставит `Dialog.analysis_status=completed`. До этого GET отчёт не возвращает.

## 2.1. Analyzer: сквозной pipeline на двух диалогах

Этот раздел показывает фактический порядок вызовов Analyzer. Здесь нет
псевдосервиса или скрытого gateway: все приведённые функции существуют в коде,
а стрелка означает непосредственный вызов следующей функции.

### Исходные условия примера

Предположим, Analyzer запущен в понедельник до 18:00 UTC со следующими
настройками:

```env
ANALYZED_MANAGER_IDS=00000001,00000002
PROMPT_ANALYZER_MANAGER_IDS=00000001,00000002
AUDIO_ANALYZER_MANAGER_IDS=00000002
FAQ_ANALYZER_MANAGER_IDS=00000002
GIGACHAT_MAX_CONCURRENCY=1
WORKER_CLAIM_LIMIT=100
```

Таким образом:

- менеджеру `00000001` назначен только Prompt-анализ;
- менеджеру `00000002` назначена обязательная цепочка Prompt → Audio → FAQ;
- worker может забрать из БД сразу оба задания, но semaphore пропустит только
  одну полную цепочку за раз.

Data Cleaner последовательно отправляет два очищенных объекта:

```python
dialog_1 = CleanedDialog(
    call_id="call-001",
    manager_id="00000001",
    manager_name="Иван",
    client_epk="epk-101",
    cleaner_version="v1",
    participants=[...],
    cleaned_text=(
        "Сотрудник: Добрый день! Чем могу помочь? "
        "Клиент: Подскажите условия вклада. Сотрудник: Конечно, расскажу."
    ),
    utterances=[...],
    source_metadata={"source": "salute-speech"},
)

dialog_2 = CleanedDialog(
    call_id="call-002",
    manager_id="00000002",
    manager_name="Анна",
    client_epk="epk-202",
    cleaner_version="v1",
    participants=[...],
    cleaned_text=(
        "Сотрудник: Алло. Клиент: Хочу закрыть карту. "
        "Сотрудник: Назовите причину, и я проверю возможные варианты."
    ),
    utterances=[...],
    source_metadata={"source": "salute-speech"},
)
```

Поля `participants`, `utterances` и `source_metadata` сокращены только в
примере. В реальном callback они проходят Pydantic-валидацию полностью.

### Короткий call graph одного диалога

```text
POST /internal/v1/dialogs/cleaned
└─ cleaned_dialog(payload, request)
   └─ DialogIntakeService.accept(payload)
      ├─ resolve_work_date(now_utc)
      ├─ Settings.analyzers_for(payload.manager_id)
      ├─ DialogRepository.save_cleaned_dialog(...)
      └─ AnalysisWorker.enqueue("dialog", call_id, manager_id, payload)
         └─ AnalysisTaskRepository.enqueue(...)

AnalysisWorker.run()
└─ AnalysisTaskRepository.claim(limit)
   └─ AnalysisWorker._run_with_limit(task)
      └─ asyncio.Semaphore
         └─ AnalysisWorker._process(task)
            └─ DialogAnalysisOrchestrator.process(call_id)
               ├─ DialogRepository.get(call_id)
               ├─ DialogRepository.mark_processing(call_id)
               ├─ PromptDialogAnalyzer.analyze(dialog)
               │  ├─ PromptAnalysisAgent.analyze(cleaned_text)
               │  │  ├─ PromptLoader.render_dialog(cleaned_text)
               │  │  ├─ выбранный LLM provider.chat_structured(...)
               │  │  │  └─ _with_attempts → _post_once → _access_token
               │  │  └─ PromptAnalysisAgent._validate_result(...)
               │  └─ calculate_q_score(results, criteria_by_code)
               ├─ ExternalAnalyzerAgent.analyze(payload)  # если нужен Audio
               ├─ ExternalAnalyzerAgent.analyze(payload)  # если нужен FAQ
               └─ DialogRepository.complete_analysis(...)
            └─ AnalysisTaskRepository.set_status(task.id, "completed")
```

Далее этот graph разобран по шагам с фактическими аргументами.

### Этап 0. Создание объектов при старте приложения

[`lifespan()`](analyzer/app/main.py) выполняется один раз при старте pod. Он
создаёт и связывает объекты, которыми затем пользуются все запросы:

```python
prompt_loader = PromptLoader()
provider = create_llm_provider(settings)

dialog_repository = DialogRepository()
task_repository = AnalysisTaskRepository()
report_repository = ReportRepository()

prompt_agent = PromptAnalysisAgent(prompt_loader, provider)
report_agent = ReportAgent(prompt_loader, provider)
prompt_dialog_analyzer = PromptDialogAnalyzer(prompt_loader, prompt_agent)

dialog_orchestrator = DialogAnalysisOrchestrator(
    repository=dialog_repository,
    prompt_analyzer=prompt_dialog_analyzer,
    external_analyzers={"audio": audio_agent, "faq": faq_agent},
)

worker = AnalysisWorker(
    settings=settings,
    tasks=task_repository,
    dialogs=dialog_repository,
    reports=report_repository,
    dialog_orchestrator=dialog_orchestrator,
    report_orchestrator=report_orchestrator,
)
```

`PromptLoader.__init__()` в этот момент читает с диска:

- `dialog_system.md` и `dialog_user.md`;
- четыре пары промптов агрегированных отчётов;
- все YAML-файлы критериев.

После старта промпты берутся из памяти. На каждый звонок файлы заново не
читаются. `asyncio.create_task(worker.run())` запускает фоновый цикл очереди, а
`scheduler.start()` регистрирует расписания агрегатов.

### Этап 1. Callback принимает первый диалог

FastAPI вызывает
[`cleaned_dialog(payload, request)`](analyzer/app/api/callbacks.py), где:

```python
payload.call_id == "call-001"
payload.manager_id == "00000001"
payload.cleaned_text == "Сотрудник: Добрый день!..."
```

До входа в функцию Pydantic-модель `CleanedDialog` проверяет обязательные поля,
непустой текст и восьмизначный `manager_id`. Невалидный HTTP body получает
`422`; бизнес-логика ещё не вызывается.

Валидный объект передаётся без преобразований:

```python
outcome = await dialog_intake.accept(payload=dialog_1)
```

HTTP-ручка не анализирует текст и не вызывает GigaChat. Её задача — передать
управление сервису и вернуть `202`.

### Этап 2. Intake решает, нужен ли анализ

[`DialogIntakeService.accept(payload)`](analyzer/app/services/dialog_intake.py)
последовательно выполняет две проверки.

Первая проверка:

```python
work_date = resolve_work_date(received_at=datetime.now(UTC))
```

[`resolve_work_date()`](analyzer/app/services/calendar_policy.py) возвращает
рабочую дату либо `None`. Важно: сейчас используется время получения callback,
а не `payload.occurred_at`.

- понедельник–четверг до 18:00 UTC → текущая дата;
- понедельник–четверг после 18:00 UTC → следующий день;
- пятница после 18:00 UTC и суббота → `None`;
- воскресенье после 18:00 UTC → следующий понедельник;
- воскресенье до 18:00 UTC → `None`.

Если получен `None`, функция сразу возвращает `"calendar_filtered"`. API всё
равно отвечает `202`, но строки в `dialogs` и задания в `analysis_tasks` не
создаются.

Вторая проверка:

```python
required_analyzers = settings.analyzers_for("00000001")
# ("prompt",)
```

Для второго диалога результат другой:

```python
required_analyzers = settings.analyzers_for("00000002")
# ("prompt", "audio", "faq")
```

Если менеджера нет в `ANALYZED_MANAGER_IDS`, возвращается
`"manager_filtered"`: callback получает `202`, но диалог намеренно исчезает из
pipeline. Если менеджер включён, но ему не назначен ни один анализатор,
`accept()` возбуждает `ValueError`, а API отвечает `422`.

### Этап 3. Диалог и задание сохраняются отдельно

Для `call-001` intake сначала вызывает:

```python
await dialog_repository.save_cleaned_dialog(
    payload=dialog_1,
    work_date=date(2026, 10, 19),
    required_analyzers=("prompt",),
    criteria_version="prompt-4q-v1",
    model_name=settings.selected_llm_model,
    prompt_version="prompt-4q-v1",
)
```

[`save_cleaned_dialog()`](analyzer/app/database/repositories/dialog_repository.py)
за одну транзакцию:

1. собирает реплики, тайм-коды и эмоции в `dialog_data`;
2. вставляет одну строку `analyzer.dialogs` со статусом `waiting`;
3. при повторном `call_id` ничего не дублирует благодаря
   `ON CONFLICT DO NOTHING`.

После этого вызывается:

```python
await worker.enqueue(
    task_type="dialog",
    entity_key="call-001",
    manager_id="00000001",
    payload={"required_analyzers": ("prompt",)},
)
```

[`AnalysisWorker.enqueue()`](analyzer/app/services/analysis_worker.py) добавляет
приоритет `10` и передаёт запись в
[`AnalysisTaskRepository.enqueue()`](analyzer/app/database/repositories/analysis_task_repository.py):

```python
AnalysisTask(
    task_type="dialog",
    entity_key="call-001",
    manager_id="00000001",
    status="waiting",
    priority=10,
    report_version="v1",
    payload={"required_analyzers": ["prompt"]},
)
```

Для `call-002` создаются такие же две строки, но
`required_analyzers=["prompt", "audio", "faq"]`.

`Dialog` — данные и результат звонка. `AnalysisTask` — техническое письмо
worker: что именно нужно запустить. Эти строки не дублируют друг друга по
назначению.

### Этап 4. Worker забирает задания

[`AnalysisWorker.run()`](analyzer/app/services/analysis_worker.py) живёт, пока
работает приложение:

```python
await task_repository.recover_processing()

while running:
    tasks = await task_repository.claim(limit=WORKER_CLAIM_LIMIT)
    if not tasks:
        await asyncio.sleep(WORKER_POLL_INTERVAL_SECONDS)
        continue
    await asyncio.gather(*(_run_with_limit(task) for task in tasks))
```

При старте
[`recover_processing()`](analyzer/app/database/repositories/analysis_task_repository.py)
возвращает зависшие после падения pod строки `processing` обратно в `waiting`.

[`claim(limit=100)`](analyzer/app/database/repositories/analysis_task_repository.py)
выбирает задания по `priority`, затем по времени создания, используя
`FOR UPDATE SKIP LOCKED`, и меняет их статус на `processing`. В памяти worker
получает Pydantic-объекты:

```python
task_1 = AnalysisTaskEntity(
    id=UUID("..."),
    task_type="dialog",
    entity_key="call-001",
    manager_id="00000001",
    payload={"required_analyzers": ["prompt"]},
)

task_2 = AnalysisTaskEntity(
    id=UUID("..."),
    task_type="dialog",
    entity_key="call-002",
    manager_id="00000002",
    payload={"required_analyzers": ["prompt", "audio", "faq"]},
)
```

`asyncio.gather()` создаёт две корутины, но каждая входит в
`_run_with_limit(task)`. При `GIGACHAT_MAX_CONCURRENCY=1` первая корутина
захватывает semaphore, а вторая ждёт. Поэтому параллельно не исполняются две
полные цепочки, даже если worker забрал обе строки одним SQL-запросом.

### Этап 5. Worker выбирает тип pipeline

Под semaphore вызывается `_process(task_1)`. Условие:

```python
if task.task_type == "dialog":
    await dialog_orchestrator.process(call_id="call-001")
else:
    await report_orchestrator.build(...)
```

То есть `task_type` не является названием произвольной функции. Он выбирает
один из двух верхнеуровневых путей:

- `dialog` → анализ одного звонка;
- `daily`, `weekly`, `four_week`, `quarterly` → агрегированный отчёт.

### Этап 6. Оркестратор читает обязательную цепочку из Dialog

[`DialogAnalysisOrchestrator.process(call_id)`](analyzer/app/services/dialog_analysis_orchestrator.py)
получает только `call_id` и сам загружает доменную сущность:

```python
dialog = await dialog_repository.get("call-001")
await dialog_repository.mark_processing("call-001")
```

В памяти появляется `DialogEntity` с текстом, метаданными и
`required_analyzers`. В БД `dialogs.analysis_status` становится `processing`.

Оркестратор создаёт временные аккумуляторы:

```python
results = {}
criteria = []
q_score = None
critical_violation = False
```

Затем проходит строго по сохранённому списку:

```python
for analyzer_name in dialog.required_analyzers:
    step = self._steps[analyzer_name]
    result = await step(dialog)
```

Для `call-001` цикл содержит один шаг. Для `call-002` — три последовательных
шага. Следующий анализатор не запускается, пока предыдущий не вернул результат.

### Этап 7. Prompt-анализ одного диалога

Первый `step` —
[`PromptDialogAnalyzer.analyze(dialog)`](analyzer/app/services/prompt_dialog_analyzer.py):

```python
response = await prompt_agent.analyze(
    dialog_text=dialog.cleaned_text,
)
```

[`PromptAnalysisAgent.analyze()`](analyzer/app/agents/prompt_analysis_agent.py)
вызывает:

```python
system_prompt, user_prompt = prompt_loader.render_dialog(dialog_text)
```

[`PromptLoader.render_dialog()`](analyzer/app/agents/prompt_loader.py) берёт из
памяти активные определения критериев, удаляет из передаваемого модели JSON внутренние
поля `penalty` и `critical`, вкладывает каталог критериев и полный цельный текст
диалога в `dialog_user.md`.

Далее агент выполняет:

```python
result = await provider.chat_structured(
    system_prompt=system_prompt,
    user_prompt=user_prompt,
    response_model=DialogAnalysisResponse,
)
```

[`GigaChatProvider.chat_structured()`](analyzer/app/agents/gigachat_provider/gigachat_provider.py)
формирует запрос с `model`, `max_tokens`, `temperature` либо `top_p`,
`repetition_penalty` и строгой JSON Schema модели `DialogAnalysisResponse`.

Внутренний путь запроса:

```text
chat_structured()
└─ _completion_payload()
   └─ _with_attempts(operation)
      └─ _post_once("/chat/completions", payload)
         ├─ provider semaphore
         ├─ _access_token()
         └─ HTTP POST в GigaChat
```

`_access_token()` переиспользует действующий токен. Если токена нет или он
истекает менее чем через 30 секунд, только одна корутина обновляет его под
`_access_token_lock`.

На сетевой ошибке, невалидном JSON или несовпадении Pydantic-схемы
`_with_attempts()` повторяет запрос до `GIGACHAT_MAX_ATTEMPTS` раз с
экспоненциальной задержкой, ограниченной 20 секундами. После последней попытки
возбуждается `GigaChatError`.

Успешный сокращённый ответ для `call-001` при полном каталоге выглядит так:

```python
DialogAnalysisResponse(
    results=[
        CriterionResult(
            code="GENERAL_01",
            score=1,
            recommendation="Приветствие выполнено корректно.",
        ),
        CriterionResult(
            code="GENERAL_02",
            score=0,
            recommendation=(
                "В реплике «Конечно, расскажу» не уточнена цель клиента. "
                "Сначала задайте уточняющий вопрос."
            ),
        ),
        # ...ещё 25 обязательных результатов
    ]
)
```

После HTTP-ответа
`PromptAnalysisAgent._validate_result(result, dialog_text)` проверяет:

1. коды критериев не повторяются;
2. модель вернула ровно тот же набор кодов, что загружен из YAML;
3. при `score=0` рекомендация содержит цитату;
4. цитата буквально присутствует в `cleaned_text`.

Любое нарушение контракта считается ошибкой всего анализа, а не частичным
успехом.

Затем [`calculate_q_score(results, criteria_by_code)`](analyzer/app/services/scoring.py)
считает оценку приложением:

```python
violations = [criterion for criterion in results if criterion.score == 0]
penalty_sum = sum(yaml_definition.penalty for criterion in violations)
q_score = max(0, 100 - penalty_sum)

if есть_критическое_нарушение:
    q_score = min(q_score, 80)
```

`PromptDialogAnalyzer` возвращает унифицированный `AnalyzerStepResult`:

```python
AnalyzerStepResult(
    analyzer="prompt",
    payload={"criteria": [...]},
    q_score=90.0,
    critical_violation=False,
    criteria=[...],
)
```

Оркестратор пока держит этот результат в оперативной памяти. Статус диалога
ещё не `completed`.

### Этап 8. Разница между двумя менеджерами

Для `call-001` список `required_analyzers` закончился. Оркестратор переходит к
сохранению.

Для `call-002` после Prompt запускается сгенерированная функция-обёртка
`_external_step(audio_agent)`, а затем `_external_step(faq_agent)`. Каждая
вызывает:

```python
await external_agent.analyze(
    payload={
        "call_id": "call-002",
        "manager_id": "00000002",
        "work_date": "2026-10-19",
        "cleaned_text": "Сотрудник: Алло...",
        "dialog_data": [...],
    }
)
```

[`ExternalAnalyzerAgent.analyze()`](analyzer/app/agents/external_analyzer_agent.py)
делает `POST {AUDIO_ANALYZER_URL|FAQ_ANALYZER_URL}/internal/v1/analyze`.
Ожидаемый ответ:

```json
{
  "status": "completed",
  "result": {"someAnalyzerField": "value"}
}
```

Если HTTP-код ошибочный, превышен timeout, JSON не соответствует
`ExternalAnalyzerResponse` или `status != "completed"`, возбуждается исключение.
FAQ после ошибки Audio уже не вызывается. В текущей реализации внешний Audio/
FAQ вызов не имеет собственных пяти повторов: пять попыток относятся к
GigaChatProvider.

Успешные результаты накапливаются так:

```python
results = {
    "prompt": {"criteria": [...]},
    "audio": {"someAnalyzerField": "value"},
    "faq": {"someOtherField": "value"},
}
```

### Этап 9. Атомарное завершение анализа диалога

Только после последнего обязательного анализатора вызывается:

```python
await dialog_repository.complete_analysis(
    call_id="call-002",
    analysis_results=results,
    q_score=87.0,
    critical_violation=False,
)
```

Метод блокирует строку `dialogs` через `FOR UPDATE` и одним commit записывает
результаты, Q-score, флаг критического нарушения, `completed_at` и
`analysis_status="completed"`.

После возвращения из оркестратора worker завершает техническое письмо:

```python
await task_repository.set_status(task.id, status="completed")
```

Semaphore освобождается, и может стартовать цепочка следующего диалога. При
лимите `1` полный порядок примера будет таким:

```text
call-001: Prompt → save completed
call-002: Prompt → Audio → FAQ → save completed
```

При лимите `2` обе цепочки могут выполняться одновременно, но внутри
`call-002` порядок Prompt → Audio → FAQ останется последовательным.

### Этап 10. Общая аварийная ветка worker

Любое необработанное исключение из `DialogAnalysisOrchestrator` попадает в
`AnalysisWorker._process()`:

```python
except Exception as exc:
    error_code = type(exc).__name__
    await task_repository.set_status(
        task.id,
        status="failed",
        error_code=error_code,
        attempt_count=attempts,
    )
    await dialog_repository.mark_failed(call_id, error_code)
```

В результате:

- `analysis_tasks.status = failed`;
- `dialogs.analysis_status = failed`;
- технический класс ошибки остаётся в `error_code`;
- worker не падает и продолжает обрабатывать следующую строку;
- публичный GET отвечает `404`, потому что читает только `completed`.

Если pod упал, когда task уже был `processing`, но код ещё не успел записать
`completed` или `failed`, следующий старт вызывает `recover_processing()` и
возвращает task и результат в `waiting`.

Отдельный пограничный случай текущей реализации: сохранение `dialogs` и
создание `analysis_tasks` происходят в двух транзакциях. Если диалог уже
сохранён, а `worker.enqueue()` упал, callback вернёт `500`, но строка диалога
останется без задания. Автоматического поиска таких строк сейчас нет; её можно
повторно поставить через `POST /analysis/run/dialog` либо исправить вручную.

### Этап 11. Что возвращает GET

Запрос:

```http
GET /manager/dialogs/call-002
```

идёт по цепочке:

```text
get_dialog_report(call_id, request)
└─ ManagerService.dialog_report("call-002")
   └─ DialogRepository.get_completed("call-002")
```

[`get_completed()`](analyzer/app/database/repositories/dialog_repository.py)
добавляет SQL-условие `analysis_status = 'completed'`. Поэтому промежуточные и
неуспешные результаты принципиально не выходят наружу. Успешный ответ содержит
Q-score, результаты всех активных критериев и payload каждого обязательного
анализатора.

## 2.2. Продолжение примера: от диалогов до квартального отчёта

Агрегированный pipeline использует ту же очередь `analysis_tasks`, тот же
worker и тот же semaphore. Разница начинается только внутри `_process()`, где
тип задания уже не `dialog`.

### Daily: из нескольких диалогов одного менеджера

В 18:00 UTC APScheduler вызывает
[`ReportScheduler.enqueue_daily(work_date=None)`](analyzer/app/services/scheduler.py).
Для конкретного дня функция выполняет:

```python
managers = await report_repository.managers_with_completed_dialogs(
    work_date=date(2026, 10, 19),
)
# ["00000001", "00000002"]
```

В выборку входят только `completed`-диалоги, ещё не привязанные к дневному
отчёту. Для каждого менеджера scheduler создаёт отдельное задание:

```python
await worker.enqueue(
    task_type="daily",
    entity_key="00000001:2026-10-19",
    manager_id="00000001",
    payload={
        "period_start": "2026-10-19",
        "period_end": "2026-10-19",
    },
)
```

Scheduler на этом заканчивает работу: он не читает тексты и не вызывает LLM.
Позже `AnalysisWorker.claim()` забирает `daily` task, а `_process()`
вызывает:

```python
await report_orchestrator.build(
    report_type="daily",
    manager_id="00000001",
    period_start=date(2026, 10, 19),
    period_end=date(2026, 10, 19),
)
```

[`ReportOrchestrator.build()`](analyzer/app/services/report_orchestrator.py)
диспетчеризует его в `build_daily()`, затем в общий `_build()`.

`_load_sources()` вызывает:

```python
dialogs = await report_repository.daily_sources(
    manager_id="00000001",
    work_date=date(2026, 10, 19),
)
```

Репозиторий выбирает завершённые строки этого менеджера и дня, у которых
`daily_report_id IS NULL`. `_dialog_sources(dialogs)` превращает каждую строку
в неделимый JSON-элемент:

```python
items = [
    '{"call_id":"call-001","q_score":90.0,"criteria":[...]}',
    '{"call_id":"call-003","q_score":80.0,"criteria":[...]}',
]

source_data = ReportSourceData(
    items=items,
    score_sum=170.0,
    communications_count=2,
    source_ids=["call-001", "call-003"],
    criteria={
        "GENERAL_01": {
            "passed_count": 2,
            "violation_count": 0,
            "communications_count": 2,
        },
        # ...
    },
)
```

Числовые показатели рассчитываются кодом. LLM не определяет daily
Q-score: после сохранения он будет равен `170 / 2 = 85`.

### Как строятся token-aware батчи

Общий `_build()` рассчитывает доступный бюджет:

```python
available_tokens = (
    GIGACHAT_MAX_INPUT_TOKENS
    - GIGACHAT_PROMPT_RESERVE_TOKENS
    - GIGACHAT_OUTPUT_RESERVE_TOKENS
)
```

Затем вызывает
[`build_recommendation_with_batches()`](analyzer/app/services/batching.py):

```python
summary = await build_recommendation_with_batches(
    provider=provider,
    agent=report_agent,
    items=source_data.items,
    report_type="daily",
    max_tokens=available_tokens,
    max_items=15,
)
```

Функция делает отдельный `provider.count_tokens([item])` для каждого цельного
элемента. [`balanced_contiguous()`](analyzer/app/services/batching.py) делит
только между элементами: содержимое одного диалога или нижележащего отчёта
никогда не разрезается.

Для 16 примерно одинаковых диалогов результат будет `[8, 8]`. Для каждого
батча последовательно вызывается:

```python
await report_agent.build_recommendation(
    items=batch,
    report_type="daily_batch",
)
```

[`ReportAgent.build_recommendation()`](analyzer/app/agents/report_agent.py)
вызывает `PromptLoader.render_aggregate("daily_batch", items)`. Loader выбирает
именно `daily_system.md`/`daily_user.md`, потому что строка начинается с
`daily`, после чего `GigaChatProvider.chat_structured()` возвращает строгий
`AggregatedRecommendation(summary=...)`.

Если батчей несколько, их текстовые рекомендации становятся новыми неделимыми
элементами, и функция рекурсивно строит `daily_merge`. Если один исходный
элемент сам превышает лимит токенов, возникает `TokenBudgetExceededError`, а
daily task и `daily_reports` переходят в `failed`.

### Сохранение daily

После получения summary вызывается:

```python
await report_repository.save_completed(
    report_type="daily",
    manager_id="00000001",
    start=date(2026, 10, 19),
    end=date(2026, 10, 19),
    report_version="v1",
    score_sum=170.0,
    communications_count=2,
    summary="Менеджер корректно приветствует клиентов, но...",
    details={"source_count": 2, "criteria": {...}},
    source_ids=["call-001", "call-003"],
)
```

В одной транзакции `save_completed()`:

1. находит существующий отчёт через `_find_report()` либо создаёт его;
2. рассчитывает `q_score = score_sum / communications_count`;
3. записывает summary и агрегаты критериев;
4. `_bind_sources()` ставит выбранным диалогам `daily_report_id`;
5. `_set_source_ids()` записывает call ID в `daily_reports.source_call_ids`;
6. выставляет `status="completed"`.

Если сохранение одного менеджера упало, его task получает `failed`. Задания
других менеджеров независимы и продолжают выполняться.

### Weekly: из дневных отчётов

В субботу `ReportScheduler.enqueue_weekly()` вычисляет понедельник и пятницу
завершившейся рабочей недели. Затем:

```text
managers_with_completed_reports("daily", monday, friday)
→ worker.enqueue("weekly", ...)
→ worker.claim(...)
→ ReportOrchestrator.build("weekly", manager_id, monday, friday)
→ build_weekly(...)
→ _load_sources(...)
→ ReportRepository.period_sources(child_type="daily", ...)
```

`period_sources()` читает только `daily_reports.status="completed"` и
`weekly_report_id IS NULL`. Отсутствующий день не получает искусственные 100
баллов: он просто не входит в источники. `_report_sources()` складывает
`score_sum` и `communications_count` всех дневных отчётов, поэтому weekly
Q-score остаётся взвешенным по количеству реальных звонков.

Далее применяется тот же token count → batching → `weekly` prompt →
`save_completed()` pipeline. В конце дневные источники получают
`weekly_report_id`.

### Four-week: строго из четырёх недель

Сразу после успешного weekly worker вызывает
`ReportPromotionService.after_completed()`. Сервис проверяет:

```python
await report_promotion.after_completed("weekly", manager_id)
```

Сервис получает все ещё не использованные weekly через
`unconsumed_reports(manager_id, "weekly")`. `_first_consecutive(reports, 4)`
ищет первые четыре последовательных периода. Если их только три, функция
возвращает пустой список и task не создаётся — отчёты остаются ждать следующую
неделю.

При четырёх периодах создаётся `four_week` task. Внутри ReportOrchestrator есть
повторная защита: `REQUIRED_SOURCE_COUNTS["four_week"] == 4`. Если между
постановкой task и исполнением источники исчезли или были заняты другим
отчётом, `_build()` завершится ошибкой «Недостаточно отчётов предыдущего
уровня».

Успешная цепочка снова выглядит одинаково:

```text
4 weekly → _report_sources → token count/batches
→ four_week_system.md + four_week_user.md
→ LLM summary
→ four_week_reports
→ weekly_reports.four_week_report_id
```

### Quarterly: строго из трёх four-week

После успешного four-week используется тот же событийный вызов:

```python
await report_promotion.after_completed("four_week", manager_id)
```

Логика полностью симметрична four-week: три последовательных неиспользованных
`four_week_reports` превращаются в один quarterly task, затем в
`quarterly_reports`. Источники получают `quarterly_report_id`. Числовой Q-score
по-прежнему считается из `score_sum / communications_count`; LLM создаёт
только итоговую рекомендацию по `quarterly`-промпту.

### Сводная причинно-следственная цепочка агрегатов

```text
completed dialogs менеджера за день
└─ daily task
   └─ daily_reports
      └─ completed daily за понедельник–пятницу
         └─ weekly task
            └─ weekly_reports
               └─ 4 последовательных неиспользованных weekly
                  └─ four_week task
                     └─ four_week_reports
                        └─ 3 последовательных неиспользованных four-week
                           └─ quarterly task
                              └─ quarterly_reports
```

На каждом уровне действует одно правило видимости: наружу выдаётся только
`completed`. Любая ошибка проходит через общую ветку
`AnalysisWorker._mark_result_failed()`, которая вызывает
`ReportRepository.mark_failed()` для конкретного менеджера и конкретного
периода. Нижележащие завершённые отчёты при этом не удаляются.

## 3. Хранение Analyzer

Модели описаны в
[`analyzer/app/database/models.py`](analyzer/app/database/models.py), SQL-запросы
изолированы в [`database/repositories`](analyzer/app/database/repositories/).

### `analyzer.dialogs`

Одна строка содержит как очищенный звонок, так и итог его анализа:

- нормализованный текст и `dialog_data` с репликами, тайм-кодами и эмоциями;
- список обязательных анализаторов;
- единый `analysis_results` с результатами Prompt/Audio/FAQ;
- Q-score, critical flag, status и error code;
- ссылку на дневной отчёт, в который вошёл звонок.

Отдельной таблицы реплик нет. Критерии находятся по пути
`analysis_results.prompt.criteria`, без дублирующей колонки.

### Отдельные таблицы отчётов

- `analyzer.daily_reports` — результат дня и `source_call_ids`;
- `analyzer.weekly_reports` — результат недели и `source_daily_report_ids`;
- `analyzer.four_week_reports` — четыре недели и `source_weekly_report_ids`;
- `analyzer.quarterly_reports` — три four-week отчёта и
  `source_four_week_report_ids`.

Источник дополнительно получает внешний ключ на родительский отчёт. Поэтому БД
не выбирает один нижележащий отчёт повторно, а запросы не фильтруют универсальную
таблицу по строковому `report_type`.

## 4. Агрегированные отчёты

Все точки запуска явно собраны в
[`ReportOrchestrator`](analyzer/app/services/report_orchestrator.py):

- `build_daily()` читает завершённые `dialogs` выбранного дня;
- `build_weekly()` читает дневные отчёты понедельника–пятницы;
- `build_four_week()` требует ровно четыре неиспользованных weekly;
- `build_quarterly()` требует ровно три неиспользованных four-week.

Q-score агрегата рассчитывается приложением как взвешенная сумма Q-score
нижнего уровня, разделённая на число коммуникаций. LLM создаёт только
текстовую рекомендацию.

Для каждого уровня существует отдельная пара промптов:

- [`daily_system.md`](analyzer/app/agents/prompts/daily_system.md) и
  [`daily_user.md`](analyzer/app/agents/prompts/daily_user.md);
- [`weekly_system.md`](analyzer/app/agents/prompts/weekly_system.md) и
  [`weekly_user.md`](analyzer/app/agents/prompts/weekly_user.md);
- [`four_week_system.md`](analyzer/app/agents/prompts/four_week_system.md) и
  [`four_week_user.md`](analyzer/app/agents/prompts/four_week_user.md);
- [`quarterly_system.md`](analyzer/app/agents/prompts/quarterly_system.md) и
  [`quarterly_user.md`](analyzer/app/agents/prompts/quarterly_user.md).

### Token count и батчи

Алгоритм расположен в
[`analyzer/app/services/batching.py`](analyzer/app/services/batching.py):

1. Для каждого цельного диалога или нижележащего отчёта считается размер:
   GigaChat использует `/tokens/count`, Ollama — консервативную локальную оценку
   по количеству символов без дополнительной генерации.
2. Источники делятся на максимально равные последовательные батчи с учётом
   лимита токенов и `AGGREGATION_MAX_BATCH_ITEMS`.
3. Источник никогда не разрезается внутри.
4. Каждый батч получает рекомендацию.
5. Если батчей несколько, их рекомендации рекурсивно объединяются тем же
   уровневым промптом.

Например, 16 одинаковых диалогов при лимите 15 делятся на 8 + 8, а не 15 + 1.

## 5. Расписание и ручной запуск

[`ReportScheduler`](analyzer/app/services/scheduler.py) регистрируется при старте
Analyzer в [`main.py`](analyzer/app/main.py).

- Daily: понедельник–пятница, `DAILY_REPORT_CRON_HOUR_UTC`, по умолчанию 18:00.
- Weekly: суббота, `WEEKLY_REPORT_CRON_HOUR_UTC`.
- Four-week и quarterly создаются событием сразу после готовности нижнего уровня.

Scheduler сам не вызывает LLM и не меняет отчёты. Он только создаёт
`AnalysisTask`, которую затем забирает общий worker.

Для тестирования те же сценарии доступны вручную в
[`analyzer/app/api/runs.py`](analyzer/app/api/runs.py):

- `POST /analysis/run/dialog`;
- `POST /analysis/run/daily`;
- `POST /analysis/run/weekly`;
- `POST /analysis/run/four-week`;
- `POST /analysis/run/quarterly`.

## 6. GET и видимость ошибок

Публичные ручки находятся в
[`analyzer/app/api/manager.py`](analyzer/app/api/manager.py), сборка ответа — в
[`ManagerService`](analyzer/app/services/manager_service.py).

- `GET /manager/dialogs/{call_id}` возвращает только полностью завершённый
  анализ звонка.
- `GET /manager/{manager_id}/dialogs?date=YYYY-MM-DD` возвращает завершённый
  дневной отчёт и вошедшие в него звонки.
- `GET /manager/{manager_id}/dates?from=...&to=...` возвращает доступные даты.

Статусы `waiting`, `processing` и `failed` наружу не показываются — API отвечает
`404`. Техническая ошибка остаётся в `dialogs`, таблице соответствующего отчёта
и `analysis_tasks` для диагностики.

## 7. Что хранится в памяти, а что в БД

| Этап | Оперативная память | PostgreSQL |
|---|---|---|
| Kafka получает чанк | Текущий ProtoBuf/Pydantic объект | Все незавершённые чанки |
| Пришёл `is_last` | Полный диалог на время сборки и HTTP | Чанки уже удалены |
| Cleaner принял `202` | HTTP request | Задание очистки |
| Cleaner обрабатывает | Расшифрованный и очищенный объект | Исходное задание до конца обработки |
| Analyzer отбирает менеджера | Callback payload | Ничего, если менеджер выключен; иначе `dialogs` + `analysis_tasks` |
| Анализ звонка | Текущий Dialog и ответы анализаторов | `dialogs.analysis_status=processing` |
| Анализ завершён | Временные результаты освобождаются | Полный итог в той же строке `dialogs` |
| Агрегат | Только выбранные источники и текущие батчи | Отдельная таблица уровня + ссылки источников |

## 8. Локальный запуск и проверки

### Что поднимает Docker Compose

Единственный `docker-compose.yml` поднимает весь локальный тракт:

```text
Kafka Producer :8083
        │ ProtoBuf, topic salute-speech, 1 partition
        ▼
Kafka :9092 → Kafka Consumer → Data Cleaner :8081 → Analyzer :8082
                              │                    │
                              ▼                    ▼
                         UCP Mock :8084       Ollama :11434
                                                   │
                                                   ▼
                                         qwen3:4b-instruct

Все три основных сервиса → PostgreSQL :5432
```

Kafka работает в KRaft-режиме без ZooKeeper. `kafka-init` один раз создаёт
ровно один topic `salute-speech` с одной partition. `ollama-pull` при первом
старте скачивает `qwen3:4b-instruct`; модель занимает примерно 2,5 ГБ, поэтому
первый запуск заметно дольше последующих. Модель хранится в Docker volume и при
обычном `docker compose down` повторно не скачивается.

Compose намеренно переопределяет локальные настройки Analyzer:

```env
LLM_PROVIDER=ollama
ACTIVE_CRITERIA_CODES=GENERAL_01,GENERAL_02,GENERAL_03
CALENDAR_FILTER_ENABLED=false
WORKER_POLL_INTERVAL_SECONDS=30
```

То есть локально проверяются представление менеджера, приветствие и тема
звонка, а календарный фильтр не мешает запуску в выходной или вечером. При
`LLM_PROVIDER=gigachat` остаётся прежний `GigaChatProvider`; его код не удалён.
Пустой `ACTIVE_CRITERIA_CODES` включает весь каталог критериев.

Compose имеет фиксированное имя проекта `nextgen-refactor`. Благодаря этому
команды управляют тем же набором контейнеров и volumes после переноса каталога
проекта в другое место.

### Первый запуск

В PowerShell из корня проекта:

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose ps
```

Если `.env` уже настроен, копировать его заново не нужно. Ход загрузки модели и
запуска сервисов виден командами:

```powershell
docker compose logs -f ollama-pull
docker compose logs -f kafka-consumer data-cleaner analyzer
```

Стек готов, когда `postgres`, `kafka`, `ollama`, `ucp-mock`, `analyzer`,
`data-cleaner` и `kafka-producer` имеют статус running/healthy, а одноразовые
`kafka-init` и `ollama-pull` завершились кодом `0`.

### Отправка цельного диалога через Swagger

Открыть в браузере:

```text
http://localhost:8083/docs
```

В `POST /dialogs` нажать **Try it out** и отправить:

```json
{
  "call_id": "manual-e2e-001",
  "manager_id": "00000001",
  "manager_name": "Алексей",
  "client_name": "Мария",
  "client_phone": "+79990000000",
  "direction": "outgoing",
  "dialog_text": "Сотрудник: Здравствуйте, меня зовут Алексей, я ваш персональный менеджер.\nКлиент: Добрый день. Хочу узнать условия вклада.\nСотрудник: Цель моего звонка — подобрать подходящий вклад. Какой срок вас интересует?",
  "chunk_max_chars": 80
}
```

Producer выполняет следующий локальный pipeline:

1. `parse_dialog()` распознаёт префиксы `Сотрудник:` и `Клиент:`;
2. длинные реплики делятся по границам слов не длиннее `chunk_max_chars`;
3. каждому фрагменту назначается последовательный `part` с нуля;
4. только последний получает `is_last=true`;
5. роли преобразуются в телефонные каналы с учётом `direction`;
6. каждый `RecognitionResponse` сериализуется в ProtoBuf;
7. сообщения с одинаковым `call_id` отправляются с одним Kafka key и сохраняют
   порядок в единственной partition.

Ответ Producer:

```json
{
  "call_id": "manual-e2e-001",
  "topic": "salute-speech",
  "chunks_sent": 4
}
```

Количество чанков зависит от текста и `chunk_max_chars`. Если строки не имеют
префикса роли, Producer чередует роли, начиная с сотрудника.

### Наблюдение за обработкой

В отдельном PowerShell:

```powershell
docker compose logs -f kafka-producer kafka-consumer data-cleaner analyzer
```

В DBeaver подключиться к:

```text
Host: localhost
Port: 55432
Database: quality
User: quality
Password: quality
```

Проверять последовательно:

- `kafka.dialog_chunks` и `kafka.dialog_state`: появляются во время сборки и
  удаляются перед отправкой полного диалога Cleaner;
- `cleaner.cleaner_jobs`: существует только до очистки и callback;
- `analyzer.dialogs`: остаётся постоянно и меняет `waiting → processing →
  completed` либо `failed`;
- `analyzer.dialogs.dialog_data`: содержит роли, текст, тайм-коды и эмоции;
- `analyzer.analysis_tasks`: хранит технический результат выполнения.

Поскольку промежуточные таблицы очищаются быстро, удобнее заранее открыть их в
DBeaver и параллельно смотреть логи. Для более медленного покадрового просмотра
можно временно увеличить `CLEANER_POLL_INTERVAL_SECONDS` или
`WORKER_POLL_INTERVAL_SECONDS` в Compose.

### Получение результата одного диалога

```powershell
Invoke-RestMethod `
  -Uri "http://localhost:8082/manager/dialogs/manual-e2e-001"
```

Пока анализ не завершён, ожидаемый ответ — `404`. После Ollama и полного
сохранения Analyzer вернёт `completed`, Q-score и три результата критериев.
Небольшая локальная модель нужна для проверки транспорта и состояний pipeline;
качество её рекомендаций не считается эквивалентом production GigaChat.

Контрольный E2E-прогон `e2e-20261023-0001` занял около 37 секунд от приёма
очищенного диалога до `completed`. Тестовый разговор был разделён на четыре
чанка и получил `qScore=100`; после завершения промежуточные записи в схемах
`kafka` и `cleaner` отсутствовали, а в `analyzer.dialogs.dialog_data` остались
четыре нормализованные реплики. Это ориентир исправного локального стенда, а не
гарантированное время ответа на другом CPU.

### Ручной запуск daily

После завершения нескольких звонков одного менеджера дневной отчёт можно
поставить без ожидания scheduler:

```powershell
$body = @{
  manager_id = "00000001"
  period_start = "2026-10-22"
  period_end = "2026-10-22"
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8082/analysis/run/daily" `
  -ContentType "application/json" `
  -Body $body
```

Дата должна совпадать с `work_date` строки в `analyzer.dialogs`. Готовый daily
читается через `GET /manager/00000001/dialogs?date=2026-10-22`.

### Остановка и полный сброс

Остановить контейнеры, сохранив PostgreSQL, Kafka и модель:

```powershell
docker compose down
```

Удалить все локальные данные и скачанную модель:

```powershell
docker compose down -v
```

Вторую команду следует использовать осознанно: после неё очищается тестовая БД
и Ollama заново скачает модель.

### Автоматические проверки

```bash
cd analyzer
uv run --extra test pytest -q
uvx ruff format --check app tests alembic
uvx ruff check app tests alembic
```

Нагрузочный smoke-сценарий находится в
[`load-tests/k6-smoke.js`](load-tests/k6-smoke.js).

## 9. Ограничения текущей версии

- Analyzer разворачивается в одной реплике, поскольку общий semaphore находится
  внутри процесса. Локальный Compose запускает ровно один Analyzer.
- Audio и FAQ сервисы подключены контрактом и оркестрацией, но их собственная
  реализация не входит в этот репозиторий.
- Бинарное аудио пока не передаётся: внешний контракт использует очищенный текст
  и структурированное поле `dialog_data`.

LEGACY_DOCUMENTATION_END -->
