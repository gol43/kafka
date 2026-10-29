# Communication Quality Analyzer

Analyzer принимает готовый обезличенный диалог от Data Cleaner, выполняет три
независимых LLM-анализа, детерминированно считает оценку и ночью подготавливает
витрину для интерфейса менеджера.

Старая цепочка daily → weekly → four-week → quarterly удалена. В проекте
остались только два тяжёлых процесса:

1. анализ одного диалога сразу после callback;
2. ежедневная сборка витрины в `18:00 UTC`.

Короткая инструкция с готовыми curl находится в
[`README_SECOND.md`](README_SECOND.md).

## 1. Архитектура

```text
Data Cleaner
    │ POST /internal/v1/dialogs/cleaned
    ▼
API → DialogIntakeService
    │ входные фильтры
    ▼
PostgreSQL: dialogs + analysis_tasks
    │
    ▼
AnalysisWorker
    │ несколько диалогов параллельно
    ▼
DialogAnalysisOrchestrator
    ├─ hygiene agent  ─┐
    ├─ deposit agent  ─┼─ последовательно для одного диалога
    └─ risk agent     ─┘
              │ общий semaphore LLM provider
              ▼
Python scoring → dialog_reports
              │
              ▼ 18:00 UTC
DashboardScheduler → DashboardBuilder
              │
              ▼
dashboard_aggregates + dashboard_snapshots
              │
              ▼
8 GET-ручек
```

Слои Analyzer:

| Каталог | Ответственность |
|---|---|
| [`analyzer/app/api`](analyzer/app/api/) | Только HTTP, параметры и status codes |
| [`analyzer/app/services`](analyzer/app/services/) | Бизнес-процесс и математика |
| [`analyzer/app/agents`](analyzer/app/agents/) | Промпты и вызовы LLM/внешних анализаторов |
| [`analyzer/app/database/repositories`](analyzer/app/database/repositories/) | Только SQL |
| [`analyzer/app/schemas`](analyzer/app/schemas/) | Pydantic-контракты |
| [`analyzer/app/database/models.py`](analyzer/app/database/models.py) | Пять ORM-таблиц |

Все зависимости собираются один раз в
[`analyzer/app/main.py`](analyzer/app/main.py). Промпты и критерии один раз
читаются с диска через
[`PromptLoader`](analyzer/app/agents/prompt_loader.py), Python-файлы не содержат
тексты промптов.

## 2. Запуск Analyzer и локальной LLM

Полный compose проекта по-прежнему находится в
[`docker-compose.yml`](docker-compose.yml). Для ручной работы только с
Analyzer добавлен [`docker-compose.analyzer.yml`](docker-compose.analyzer.yml).

Сначала поднимается PostgreSQL:

```bash
docker compose up -d postgres
```

Затем Analyzer и Ollama:

```bash
docker compose -f docker-compose.analyzer.yml up --build
```

Постоянно работают два контейнера: `analyzer` и `ollama`. Одноразовый сервис
`ollama-pull` скачивает модель и завершается. По умолчанию Analyzer подключается
к PostgreSQL на `host.docker.internal:55432`. Порт меняется через
`POSTGRES_HOST_PORT`.

Swagger:

```text
http://localhost:8082/docs
```

Логи:

```bash
docker compose -f docker-compose.analyzer.yml logs -f analyzer ollama
```

## 3. Входной callback

Endpoint реализован в
[`callbacks.py`](analyzer/app/api/callbacks.py):

```http
POST /internal/v1/dialogs/cleaned
```

Контракт находится в
[`schemas/dialogs.py`](analyzer/app/schemas/dialogs.py). Для Analyzer важны:

- `call_id`;
- `manager_id` — ровно восемь цифр;
- `client_epk`;
- `duration_seconds`;
- `occurred_at`;
- `cleaned_text` с уже размеченными ролями.

Analyzer не сохраняет ФИО, реплики, эмоции и тайм-коды. Для дальнейшего анализа
достаточно цельного `cleaned_text`. Полный входной объект живёт в памяти только
до завершения callback.

Ответ `202` означает приём callback, а не завершение LLM-анализа.

## 4. Фильтры до базы данных

[`DialogIntakeService.accept()`](analyzer/app/services/dialog_intake.py)
проверяет вход в следующем порядке.

### 4.1. Длительность

Диалог короче `MIN_DIALOG_DURATION_SECONDS=50` сразу отбрасывается. Он не
появляется ни в одной таблице и никогда не отправляется в LLM.

### 4.2. Рабочий календарь

Правило находится в
[`calendar_policy.py`](analyzer/app/services/calendar_policy.py):

| Время получения UTC | Результат |
|---|---|
| Пн–Чт до 18:00 | текущая рабочая дата |
| Пн–Чт после 18:00 | следующий день |
| Пт до 18:00 | пятница |
| Пт после 18:00 | удалить |
| Суббота | удалить |
| Воскресенье до 18:00 | удалить |
| Воскресенье после 18:00 | понедельник |

Для ручного локального E2E в compose установлен
`CALENDAR_FILTER_ENABLED=false`. В production его нужно включить.

### 4.3. Менеджер и профиль

`manager_id` должен входить в `ANALYZED_MANAGER_IDS`. Prompt Analyzer обязателен
для каждого принятого менеджера. Audio и Factor можно подключить отдельно через
ENV. Профиль вычисляет [`Settings.analyzers_for()`](analyzer/app/config.py).

Если любой фильтр не пройден, объект удаляется из памяти без INSERT.

## 5. Первое сохранение

После фильтров вызываются:

```python
saved = await dialog_repository.save_cleaned_dialog(...)
await worker.enqueue(payload.call_id)
```

Код находится в:

- [`dialog_repository.py`](analyzer/app/database/repositories/dialog_repository.py);
- [`analysis_task_repository.py`](analyzer/app/database/repositories/analysis_task_repository.py).

В одной транзакции repository создаёт `dialogs`; затем создаётся уникальная
`analysis_tasks`. Повторный callback с тем же `call_id` не создаёт дубль.

В `dialogs` сохраняются только:

```text
call_id, manager_id, client_epk, work_date, occurred_at,
duration_seconds, cleaned_text, required_analyzers,
status, error_code, версии анализа, timestamps, expires_at
```

## 6. Worker и параллельность

[`AnalysisWorker`](analyzer/app/services/analysis_worker.py) запускается в
lifespan FastAPI и бесконечно:

1. восстанавливает `processing` в `waiting` после рестарта;
2. раз в `WORKER_POLL_INTERVAL_SECONDS` читает очередь;
3. через `FOR UPDATE SKIP LOCKED` забирает backlog с `work_date <= today`;
4. помечает task и dialog как `processing`;
5. запускает до `DIALOG_PIPELINE_CONCURRENCY` диалогов параллельно.

`SKIP LOCKED` не даёт двум экземплярам worker-а забрать одну задачу.

Есть два разных ограничения:

- `DIALOG_PIPELINE_CONCURRENCY` — сколько диалоговых pipeline может работать;
- `GIGACHAT_MAX_CONCURRENCY` — сколько реальных HTTP-запросов одновременно
  допускается к сертификату/LLM.

Общий LLM semaphore находится внутри GigaChat/Ollama provider. Поэтому все
агенты используют один и тот же лимит.

## 7. Три обязательных LLM-запроса

Явная последовательность находится в
[`PromptDialogAnalyzer.analyze()`](analyzer/app/services/prompt_dialog_analyzer.py):

```python
hygiene_response = await hygiene_agent.analyze(cleaned_text)
deposit_response = await deposit_agent.analyze(cleaned_text)
risk_response = await risk_agent.analyze(cleaned_text)
```

Агенты независимы: hygiene не знает про deposits, deposits не знает про risks,
risks не знает про остальные анализы. Их объединяет только orchestrator.

Каждый ответ имеет одинаковый строгий формат:

```json
{
  "results": [
    {"code": "GENERAL_01", "score": 1, "quote": null}
  ]
}
```

`score=1` означает выполнение требования или отсутствие риска. `score=0`
означает нарушение или обнаруженный риск. Provider передаёт модели JSON Schema
Pydantic-ответа и повторяет неуспешный запрос до
`GIGACHAT_MAX_ATTEMPTS=5`.

Полные ответы LLM можно видеть в логах при `LOG_LLM_RESPONSES=true`.

Критерии лежат только в YAML:

- `analyzer/app/agents/prompts/criteria/`;
- риски — [`risks.yaml`](analyzer/app/agents/prompts/criteria/risks.yaml);
- штрафы, рекомендации и критичность дополняются из `metric_metadata.yaml`.

## 8. Вклады и риски

Во вкладовом ответе `DEPOSIT_TOPIC` является gate-критерием.

Если `DEPOSIT_TOPIC=0`:

- остальные вкладовые scores принудительно становятся `0`;
- `included_in_analytics=false`;
- блок не влияет на score;
- критерии не попадают в strengths/improvements;
- критерии не выводятся как недостатки звонка.

Если `DEPOSIT_TOPIC=1`, вкладовый score участвует в итоговой оценке.

Risk Analyzer всегда выполняется отдельно. Сейчас он ищет:

- прямое намерение клиента уйти в другой банк;
- недовольство условиями банка.

Риски не влияют на score, Q-score, strengths и improvements. Они используются
только в risk-блоках витрины и в popup отдельного диалога.

## 9. Подсчёт одного диалога

Математика находится в
[`scoring.py`](analyzer/app/services/scoring.py), модель ничего не считает:

```text
block score = 100 - сумма штрафов критериев со score=0
```

При критичном нарушении действует `CRITICAL_SCORE_CAP=80`.

```text
нет темы вкладов: final score = general score
есть тема вкладов: final score = (general score + deposit score) / 2
```

Результат popup формируется один раз в
[`dialog_report_builder.py`](analyzer/app/services/dialog_report_builder.py).
Там уже готовы итоговый score, количество отклонений, самый важный риск,
top-3 strengths и top-3 improvements.

## 10. Атомарное завершение

[`DialogRepository.complete_analysis()`](analyzer/app/database/repositories/dialog_repository.py)
в одной транзакции:

1. блокирует входной dialog;
2. вставляет или обновляет `dialog_reports`;
3. удаляет `dialogs`;
4. каскадно удаляет completed `analysis_tasks`.

В `dialog_reports` хранятся пять независимых JSONB-результатов:

```text
hygiene_results
deposit_results
risk_results
audio_results
factor_results
```

Если любой обязательный анализ окончательно упал, весь диалог становится
`failed`, готовый report не создаётся и наружу ничего не показывается. Failed
task и dialog остаются для диагностики и ручного повтора.

## 11. Сборка dashboard

[`DashboardScheduler`](analyzer/app/services/dashboard_scheduler.py) срабатывает
в `DASHBOARD_CRON_HOUR_UTC=18`. Он фиксирует cutoff и ждёт, пока все полученные
до cutoff задачи рабочей даты выйдут из `waiting/processing`.

Затем [`DashboardBuilder`](analyzer/app/services/dashboard_builder.py):

1. читает `dialog_reports` только текущей рабочей даты;
2. сохраняет дневные суммы метрик в `dashboard_aggregates`;
3. строит 30-дневное окно из дневных aggregates, а не из сырых reports;
4. считает квартальный личный Q-score;
5. считает командную медиану;
6. в пятницу сохраняет недельные проценты метрик;
7. в последний рабочий день месяца сохраняет месячный Q-score;
8. собирает готовый `dashboard_snapshots`.

LLM при построении витрины не вызывается.

### Q-score

Личный Q-score — средняя оценка завершённых диалогов с начала текущего квартала
по дату snapshot. Командный результат — медиана личных результатов всех
настроенных менеджеров. Месячные точки хранятся в JSONB aggregate.

### Риски

Окно задаётся `RISK_ROLLING_WINDOW_DAYS=10`. Выбирается максимум пять
уникальных клиентов. У клиента показывается один самый приоритетный риск:
сначала критичность, затем свежесть и количество повторений.

### Strengths и improvements

Окно — `METRIC_ROLLING_WINDOW_DAYS=30`.

```text
percent = count(score=1) / count(all applicable dialogs) * 100
```

- `percent >= 80` → strengths;
- `percent < 80` → improvements;
- в каждом блоке top-3;
- `delta` сравнивает текущий расчёт с предыдущим дневным snapshot.

Popup improvement получает недельные точки и список звонков, где метрика имела
`score=0`.

## 12. Пять таблиц

| Таблица | Назначение |
|---|---|
| `analyzer.dialogs` | Входной диалог до успешного анализа |
| `analyzer.analysis_tasks` | Персистентная очередь worker-а |
| `analyzer.dialog_reports` | Полный завершённый анализ звонка |
| `analyzer.dashboard_aggregates` | Одна строка manager/date с промежуточной JSONB-математикой |
| `analyzer.dashboard_snapshots` | Одна строка manager/date с готовыми блоками UI |

Отдельной `metric_history` нет. Метрики одного менеджера за дату хранятся одним
JSONB-объектом. TTL всех таблиц — `DATA_TTL_DAYS=183`.

Миграция новой модели:
[`analyzer_0004`](analyzer/alembic/versions/0004_two_process_architecture.py).
Она намеренно удаляет старые экспериментальные таблицы Analyzer.

## 13. Восемь GET-ручек

Routes находятся в [`manager.py`](analyzer/app/api/manager.py).

```text
GET /manager/{manager_id}/q-score?date=YYYY-MM-DD
GET /manager/{manager_id}/client-risks?date=YYYY-MM-DD
GET /manager/{manager_id}/client-risks/{client_epk}?date=YYYY-MM-DD
GET /manager/{manager_id}/strengths?date=YYYY-MM-DD
GET /manager/{manager_id}/improvements?date=YYYY-MM-DD
GET /manager/{manager_id}/improvements/{metric_code}?date=YYYY-MM-DD
GET /manager/{manager_id}/dialogs?date=YYYY-MM-DD&limit=5
GET /manager/dialogs/{call_id}
```

Дата обязательна. Первые шесть запросов делают короткий SELECT готового
`dashboard_snapshots`. Список диалогов читает `dialog_reports` и поддерживает:

- `client_epk`;
- `date_from`;
- `date_to`;
- `type=call`;
- `limit`, по умолчанию 5, максимум 100.

`waiting`, `processing`, `failed`, короткие и отфильтрованные диалоги API не
возвращает. При отсутствии полного результата используется `404`.

## 14. Ручные endpoints

Повторить failed-задачу:

```http
POST /analysis/run/dialog
{"call_id": "call-001"}
```

Построить витрину для даты:

```http
POST /analysis/run/dashboard?date=2026-10-29
```

## 15. Что находится в памяти и в БД

| Этап | Память | PostgreSQL |
|---|---|---|
| Callback до фильтров | Полный `CleanedDialog` | Ничего |
| После приёма | Объект HTTP освобождается | `dialogs`, `analysis_tasks` |
| Worker claim | Небольшая task entity | Статусы `processing` |
| Три LLM-вызова | Текст и текущие ответы | Вход и task остаются |
| Успешный commit | Готовый payload | `dialog_reports`; вход и task удалены |
| Ошибка | Exception освобождается | `dialogs/task=failed` |
| Ночная сборка | Данные одного менеджера | Aggregate и snapshot JSONB |
| GET | Один готовый объект | Один короткий SELECT |

## 16. ENV

Основные переключатели:

```env
ANALYZED_MANAGER_IDS=00000001,00000002
PROMPT_ANALYZER_MANAGER_IDS=00000001,00000002
AUDIO_ANALYZER_MANAGER_IDS=
FACTOR_ANALYZER_MANAGER_IDS=

WORKER_POLL_INTERVAL_SECONDS=30
WORKER_CLAIM_LIMIT=100
DIALOG_PIPELINE_CONCURRENCY=10
GIGACHAT_MAX_CONCURRENCY=1
GIGACHAT_MAX_ATTEMPTS=5

MIN_DIALOG_DURATION_SECONDS=50
CALENDAR_FILTER_ENABLED=true
DATA_TTL_DAYS=183

DASHBOARD_ENABLED=true
DASHBOARD_CRON_HOUR_UTC=18
DASHBOARD_WAIT_INTERVAL_SECONDS=30
METRIC_ROLLING_WINDOW_DAYS=30
RISK_ROLLING_WINDOW_DAYS=10
STRENGTH_MIN_PERCENT=80
STRENGTHS_LIMIT=3
IMPROVEMENTS_LIMIT=3
RISK_CLIENTS_LIMIT=5
LATEST_COMMUNICATIONS_LIMIT=5
COMMUNICATIONS_MAX_LIMIT=100
```

Полный список находится в [`.env.example`](.env.example) и
[`analyzer/app/config.py`](analyzer/app/config.py).
