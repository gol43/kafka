# Communication Quality Platform

Система принимает очищенную расшифровку телефонного разговора, проверяет её
через LLM, сама рассчитывает баллы и заранее готовит восемь ответов для
интерфейса менеджера.

Этот README описывает текущий рабочий путь данных. Здесь нет старой цепочки
агрегированных LLM-отчётов. Основной сценарий сейчас такой:

```text
Data Cleaner
    ↓ HTTP callback
Analyzer: проверки входа
    ↓
PostgreSQL: dialog + analysis_task
    ↓ worker
два последовательных LLM-запроса
    ↓ Python scoring
PostgreSQL: результат звонка + метрики
    ↓ ежедневная сборка витрин
PostgreSQL: готовые dashboard snapshots
    ↓
8 быстрых GET для фронтенда
```

## 1. Состав проекта

| Каталог | Назначение |
|---|---|
| [`analyzer/`](analyzer/) | Анализ звонков, расчёт оценок, подготовка витрин и API |
| [`data-cleaner/`](data-cleaner/) | Обезличивание текста и передача очищенного объекта |
| [`kafka-consumer/`](kafka-consumer/) | Чтение ProtoBuf-чанков, сборка разговора и вызов Cleaner |
| [`kafka-producer/`](kafka-producer/) | Тестовый HTTP producer для ручного E2E |
| [`postgres/`](postgres/) | Инициализация общей PostgreSQL с отдельными схемами |
| [`ucp-mock/`](ucp-mock/) | Локальная имитация UCP |
| [`load-tests/`](load-tests/) | k6 smoke-тесты |
| [`docker-compose.yml`](docker-compose.yml) | Локальный запуск всего стенда |

В текущей разработке главная часть — `analyzer`. Остальные сервисы дают ему
готовый объект звонка, но не участвуют в расчёте оценок.

## 2. Архитектура Analyzer

Код разделён по ответственности:

```text
app/api
    HTTP, параметры, коды ответа

app/services
    бизнес-процесс и расчёты

app/agents
    промпты и обращения к LLM

app/database/repositories
    только SQL-операции

app/database/models.py
    таблицы SQLAlchemy

app/schemas
    входные и выходные Pydantic-модели
```

Простое правило чтения кода:

```text
router → service → agent/repository → service → repository
```

API не считает Q-score. Agent не пишет в базу. Repository не решает, нужно ли
анализировать звонок. Каждая такая задача находится в одном слое.

Точка сборки зависимостей — [`analyzer/app/main.py`](analyzer/app/main.py).
При запуске она:

1. один раз читает ENV через `get_settings()`;
2. один раз загружает промпты через `PromptLoader`;
3. создаёт LLM provider;
4. создаёт repositories и services;
5. запускает `AnalysisWorker`;
6. запускает `DashboardScheduler`;
7. подключает API routers.

## 3. Что приходит от Data Cleaner

Analyzer принимает:

```http
POST /internal/v1/dialogs/cleaned
```

Router находится в
[`analyzer/app/api/callbacks.py`](analyzer/app/api/callbacks.py), входная модель
`CleanedDialog` — в
[`analyzer/app/schemas/dialogs.py`](analyzer/app/schemas/dialogs.py).

Пример входа:

```json
{
  "contract_version": "1.0",
  "cleaner_version": "cleaner-1",
  "call_id": "call-deposit-001",
  "manager_id": "00000001",
  "manager_name": "Анна Смирнова",
  "client_epk": "epk-ivanov-001",
  "client_fio": "Иванов Иван Иванович",
  "duration_seconds": 84,
  "occurred_at": "2026-10-26T10:15:00Z",
  "channel": "phone",
  "participants": [
    {
      "role": "employee",
      "name": "Анна Смирнова",
      "employee_id": "00000001"
    },
    {
      "role": "client",
      "name": "Иванов Иван Иванович"
    }
  ],
  "cleaned_text": "Сотрудник: Добрый день... Клиент: Хочу открыть вклад...",
  "utterances": [
    {
      "sequence_number": 0,
      "speaker_role": "employee",
      "speaker_id": 1,
      "channel": 1,
      "text": "Добрый день",
      "normalized_text": "Добрый день",
      "start_ms": 0,
      "end_ms": 1900,
      "emotions": {
        "positive": 0.7,
        "neutral": 0.3,
        "negative": 0.0
      },
      "word_alignments": []
    }
  ],
  "source_metadata": {},
  "encrypted": false
}
```

Обязательные данные для анализа:

- `call_id` — уникальный идентификатор звонка и primary key;
- `manager_id` — ровно восемь цифр;
- `client_epk` и `client_fio` — связь с клиентом;
- `cleaned_text` — текст для двух LLM-запросов;
- `duration_seconds` либо тайм-коды реплик;
- `occurred_at` — время коммуникации;
- `utterances` — реплики, роли, тайм-коды и эмоции.

Callback сразу возвращает `202`. Это значит только, что HTTP-запрос принят и
обработан входным сервисом. Сам LLM-анализ выполняется worker-ом позже.

## 4. Первый этап: входные фильтры

Router вызывает:

```python
outcome = await request.app.state.dialog_intake.accept(payload)
```

Реализация —
[`DialogIntakeService.accept()`](analyzer/app/services/dialog_intake.py).

Проверки идут строго в таком порядке.

### 4.1. Длительность

```python
duration_seconds = payload.duration_seconds
```

Если длительность не передана, берётся максимальный `utterance.end_ms` и
переводится в секунды.

```python
if duration_seconds < MIN_DIALOG_DURATION_SECONDS:
    return "duration_filtered"
```

По умолчанию минимум — 50 секунд. Такой звонок:

- не записывается в `analyzer.dialogs`;
- не получает task;
- не отправляется в LLM;
- не появляется ни в одном GET.

### 4.2. Рабочая дата

При `CALENDAR_FILTER_ENABLED=true` вызывается
[`resolve_work_date()`](analyzer/app/services/calendar_policy.py).

Если функция возвращает `None`, результат — `calendar_filtered`. Диалог в БД
Analyzer не попадает.

Если календарный фильтр выключен, используется дата `occurred_at`, а при её
отсутствии — текущее UTC-время.

### 4.3. Менеджер и профиль анализаторов

Вызывается:

```python
required_analyzers = settings.analyzers_for(payload.manager_id)
```

Логика находится в [`analyzer/app/config.py`](analyzer/app/config.py).

- менеджера нет в `ANALYZED_MANAGER_IDS` → `manager_filtered`;
- менеджер есть, но ему не назначен анализатор → `422`;
- менеджер есть в `PROMPT_ANALYZER_MANAGER_IDS` → добавляется `prompt`;
- при наличии соответствующих URL можно добавить `audio` и `faq`.

Пример:

```env
ANALYZED_MANAGER_IDS=00000001,00000002
PROMPT_ANALYZER_MANAGER_IDS=00000001,00000002
AUDIO_ANALYZER_MANAGER_IDS=
FAQ_ANALYZER_MANAGER_IDS=
```

Для обоих менеджеров получится:

```python
required_analyzers = ("prompt",)
```

До завершения этих проверок объект живёт только в памяти текущего HTTP-запроса.

## 5. Первое сохранение в PostgreSQL

После фильтров `DialogIntakeService` вызывает:

```python
await dialog_repository.save_cleaned_dialog(
    payload,
    work_date,
    required_analyzers,
    criteria_version=settings.criteria_version,
    model_name=settings.selected_llm_model,
    prompt_version=settings.prompt_version,
)
```

Repository:
[`analyzer/app/database/repositories/dialog_repository.py`](analyzer/app/database/repositories/dialog_repository.py).

Создаётся одна строка в `analyzer.dialogs`:

| Колонка | Что хранится |
|---|---|
| `call_id` | UUID/ID звонка |
| `manager_id` | табельный номер |
| `client_epk`, `client_fio` | клиент |
| `work_date`, `occurred_at` | рабочая дата и реальное время |
| `duration_seconds` | длительность |
| `cleaned_text` | цельный обезличенный текст |
| `dialog_data` | JSON-массив реплик, ролей, эмоций и тайм-кодов |
| `required_analyzers` | например `["prompt"]` |
| `analysis_status` | `waiting` |
| `criteria_version` | версия каталога критериев |
| `model_name` | GigaChat или Ollama model |
| `prompt_version` | версия промпта |

Отдельной таблицы `dialog_utterances` нет. Реплики хранятся внутри
`dialogs.dialog_data`, поэтому исходный разговор не дублируется по строкам.

INSERT идемпотентный:

```python
.on_conflict_do_nothing(index_elements=["call_id"])
```

Повторный callback с тем же `call_id` не создаёт второй диалог.

## 6. Создание задания

После сохранения вызывается:

```python
await worker.enqueue(
    "dialog",
    payload.call_id,
    payload.manager_id,
    {"required_analyzers": required_analyzers},
)
```

Цепочка:

```text
DialogIntakeService.accept
    → AnalysisWorker.enqueue
        → AnalysisTaskRepository.enqueue
            → INSERT analyzer.analysis_tasks
```

Строка задания содержит:

```text
task_type     = dialog
entity_key    = call-deposit-001
manager_id    = 00000001
status        = waiting
priority      = 10
report_version= v1
payload       = {required_analyzers: [prompt]}
```

Уникальность:

```text
(task_type, entity_key, report_version)
```

Поэтому повторный enqueue не создаёт дубль той же версии задания.

После завершения callback в памяти больше не нужно держать диалог: текст и task
уже персистентно сохранены.

## 7. Как работает worker

Worker запускается один раз в lifespan приложения:

```python
worker_task = asyncio.create_task(worker.run(), name="analysis-worker")
```

Код:
[`analyzer/app/services/analysis_worker.py`](analyzer/app/services/analysis_worker.py).

Главный цикл:

```python
while self._running:
    tasks = await self._tasks.claim(self._claim_limit)

    if not tasks:
        await asyncio.sleep(worker_poll_interval_seconds)
        continue

    await asyncio.gather(
        *(self._run_with_limit(task) for task in tasks)
    )
```

По умолчанию:

```env
WORKER_POLL_INTERVAL_SECONDS=30
WORKER_CLAIM_LIMIT=100
DIALOG_PIPELINE_CONCURRENCY=10
```

Реальный `claim_limit` вычисляется так:

```python
min(WORKER_CLAIM_LIMIT, DIALOG_PIPELINE_CONCURRENCY)
```

При значениях выше worker заберёт максимум 10 задач за один проход.

### 7.1. Безопасный claim

[`AnalysisTaskRepository.claim()`](analyzer/app/database/repositories/analysis_task_repository.py)
делает:

```sql
SELECT ...
FROM analyzer.analysis_tasks
WHERE status = 'waiting'
ORDER BY priority, created_at
LIMIT :limit
FOR UPDATE SKIP LOCKED;
```

Выбранные строки в той же транзакции становятся `processing`.

`SKIP LOCKED` нужен, чтобы два worker-а не взяли одно задание одновременно.

### 7.2. Восстановление после рестарта

При первом проходе worker вызывает:

```python
await task_repository.recover_processing()
```

Незавершённые `analysis_tasks` и `dialogs` переводятся:

```text
processing → waiting
```

После этого задача может быть взята заново. Она не теряется только из-за
перезапуска Python-процесса.

### 7.3. Два разных ограничения конкурентности

В системе два semaphore, и они решают разные задачи.

```text
dialog_pipeline_concurrency
    сколько диалогов одновременно находятся внутри полного pipeline

gigachat_max_concurrency
    сколько HTTP-запросов одновременно реально отправляется в LLM
```

Пример:

```env
DIALOG_PIPELINE_CONCURRENCY=10
GIGACHAT_MAX_CONCURRENCY=1
```

Worker может запустить 10 диалогов. Все они дойдут до LLM, но provider пропустит
наружу только один HTTP-запрос. Остальные корутины не занимают отдельные потоки:
они асинхронно ждут semaphore.

Это позволяет менять пропускную способность GigaChat через ENV, не меняя
бизнес-код.

## 8. Оркестрация одного диалога

Worker вызывает:

```python
await dialog_orchestrator.process(task.entity_key)
```

Здесь `task.entity_key` — `call_id`.

Код:
[`analyzer/app/services/dialog_analysis_orchestrator.py`](analyzer/app/services/dialog_analysis_orchestrator.py).

Последовательность:

1. `DialogRepository.get(call_id)` читает диалог;
2. `mark_processing(call_id)` ставит `dialogs.analysis_status=processing`;
3. берётся `dialog.required_analyzers`;
4. каждый обязательный анализатор вызывается последовательно;
5. при первой ошибке следующие анализаторы не запускаются;
6. при полном успехе вызывается `complete_analysis(...)`.

Пример для текущего MVP:

```python
dialog.required_analyzers == ["prompt"]
```

В будущем профиль может быть таким:

```python
["prompt", "audio", "faq"]
```

Тогда порядок будет именно `prompt → audio → faq`. Итог `completed` появится
только после успешного ответа каждого обязательного шага.

## 9. Почему на один звонок всегда два LLM-запроса

Prompt-шаг реализован в
[`PromptDialogAnalyzer.analyze()`](analyzer/app/services/prompt_dialog_analyzer.py).

Он выполняет последовательно:

```python
general_response = await agent.analyze(
    dialog.cleaned_text,
    "general",
)

deposit_response = await agent.analyze(
    dialog.cleaned_text,
    "deposit",
)
```

Первый запрос проверяет общие правила коммуникации. Второй проверяет вкладовые
критерии и обязательно возвращает технический критерий `DEPOSIT_TOPIC`.

Это два запроса даже тогда, когда разговор был не про вклад. Решение о
применимости блока принимает Python после второго ответа.

Исключение — только технический feature flag:

```env
DEPOSIT_ANALYSIS_ENABLED=false
```

При нём второй HTTP-запрос отключается, а Python создаёт локальный
`DEPOSIT_TOPIC=0`.

## 10. Как формируется промпт

Промпты загружаются один раз при старте:

[`analyzer/app/agents/prompt_loader.py`](analyzer/app/agents/prompt_loader.py).

Источники:

- [`dialog_system.md`](analyzer/app/agents/prompts/dialog_system.md) — общие правила модели;
- [`dialog_user.md`](analyzer/app/agents/prompts/dialog_user.md) — шаблон пользовательского запроса;
- [`criteria/`](analyzer/app/agents/prompts/criteria/) — описание критериев;
- [`metric_metadata.yaml`](analyzer/app/agents/prompts/metric_metadata.yaml) — веса, критичность и рекомендации;
- [`positive_templates.yaml`](analyzer/app/agents/prompts/positive_templates.yaml) — шаблоны положительного текста.

`PromptLoader.render_dialog(dialog_text, block)`:

1. выбирает критерии блока `general` либо `deposit`;
2. исключает из LLM-payload внутренние поля `penalty`, `severity`,
   `recommendation`, `topic_gate`;
3. сериализует критерии в JSON;
4. подставляет JSON и диалог в `dialog_user.md`;
5. возвращает `(system_prompt, user_prompt)`.

LLM не получает штрафы и не рассчитывает итоговую оценку. Его задача — только
классификация текста.

Через `ACTIVE_CRITERIA_CODES` можно ограничить общие критерии для локального
E2E. Вкладовый блок остаётся целым, потому что внутри него находится gate.

## 11. Контракт ответа LLM

Agent:
[`analyzer/app/agents/prompt_analysis_agent.py`](analyzer/app/agents/prompt_analysis_agent.py).

Ожидаемый результат каждого запроса:

```json
{
  "results": [
    {
      "code": "GENERAL_01",
      "score": 1,
      "quote": null
    },
    {
      "code": "GENERAL_03",
      "score": 0,
      "quote": "точная фраза из cleaned_text"
    }
  ]
}
```

Модель возвращает только:

- `code`;
- `score`, строго `0` либо `1`;
- `quote`, если есть нарушение и цитату можно выделить.

Она не возвращает штраф, severity, recommendation или Q-score.

После ответа `_validate_result(...)` проверяет:

1. нет повторяющихся кодов;
2. набор кодов полностью совпадает с отправленным каталогом;
3. цитата при `score=0`, если она дана, буквально существует в `cleaned_text`.

Некорректный JSON или неправильный набор критериев не сохраняется как успешный
анализ.

## 12. GigaChat provider

Provider выбирается в
[`analyzer/app/agents/gigachat_provider/factory.py`](analyzer/app/agents/gigachat_provider/factory.py):

```env
LLM_PROVIDER=gigachat
```

или для бесплатного локального E2E:

```env
LLM_PROVIDER=ollama
```

### 12.1. Структурированный запрос

[`GigaChatProvider.chat_structured()`](analyzer/app/agents/gigachat_provider/gigachat_provider.py)
формирует `/chat/completions`:

```json
{
  "model": "GigaChat-2-Pro",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "stream": false,
  "max_tokens": 8000,
  "repetition_penalty": 1.0,
  "response_format": {
    "type": "json_schema",
    "schema": "Pydantic JSON Schema",
    "strict": true
  }
}
```

`temperature` либо `top_p` добавляется из ENV. Одновременно задавать оба
параметра нельзя — это валидируется при старте.

### 12.2. Общий semaphore

В конструкторе provider создаётся:

```python
self._semaphore = asyncio.Semaphore(
    settings.gigachat_max_concurrency
)
```

Каждый реальный HTTP-вызов выполняется внутри:

```python
async with self._semaphore:
    ... POST /chat/completions ...
```

Оба запроса одного диалога используют этот же semaphore. Запросы других
диалогов и token count также должны использовать тот же лимит внутри одного
процесса.

Важно: semaphore локальный для процесса Analyzer. Поэтому при едином
сертификате GigaChat текущая схема предполагает один экземпляр Analyzer. Если
поднять несколько pod, у каждой будет собственный semaphore, и общий лимит
сертификата уже не гарантируется.

### 12.3. Access token

Token получается через `GIGACHAT_AUTH_URL`. Значение и срок жизни кэшируются в
памяти процесса:

```text
_access_token_value
_access_token_expires_at
```

`_access_token_lock` не даёт нескольким корутинам одновременно обновлять один
token. За 30 секунд до истечения token считается устаревшим.

Token в PostgreSQL не сохраняется.

### 12.4. Повторные попытки

Каждый LLM-запрос выполняется через `_with_attempts()`.

```env
GIGACHAT_MAX_ATTEMPTS=5
GIGACHAT_RETRY_BASE_SECONDS=1
```

Задержки:

```text
1s → 2s → 4s → 8s → ошибка
```

Задержка ограничена 20 секундами. Повторы выполняются при HTTP-ошибке,
невалидном JSON, ошибке Pydantic или отсутствии ожидаемых полей.

После исчерпания попыток выбрасывается `GigaChatError(attempts=5)`.

### 12.5. Ollama

[`OllamaProvider`](analyzer/app/agents/gigachat_provider/ollama_provider.py)
имеет тот же интерфейс, тот же semaphore, количество попыток и JSON Schema.
Поэтому переключение `gigachat ↔ ollama` не меняет services и repositories.

В текущем анализе одиночного диалога `count_tokens()` не вызывается. У GigaChat
и Ollama этот метод оставлен для будущих больших batch-запросов.

## 13. Расчёт score в Python

Формулы находятся в
[`analyzer/app/services/scoring.py`](analyzer/app/services/scoring.py).

### 13.1. Общий блок

```text
general_score = max(0, 100 - сумма штрафов критериев со score=0)
```

Если нарушен критичный общий критерий:

```text
general_score ≤ 80
```

Точное ограничение задаётся `CRITICAL_SCORE_CAP`.

### 13.2. Блок вкладов

Python находит критерий, у которого `topic_gate=true`. Сейчас это
`DEPOSIT_TOPIC`.

Если:

```text
DEPOSIT_TOPIC = 0
```

то:

- все вкладовые score принудительно становятся `0`;
- `included_in_analytics=false`;
- `deposit_score=null`;
- вкладовые критерии не входят в Q-score;
- они не попадают в риски, strengths, improvements и карточку звонка;
- итоговый score равен `general_score`.

Нули сохраняются только как технический результат ответа модели. Они не
считаются нарушениями менеджера.

Если:

```text
DEPOSIT_TOPIC = 1
```

то считается:

```text
deposit_score = max(0, 100 - сумма вкладовых штрафов)
final_score   = (general_score + deposit_score) / 2
```

Критичное нарушение ограничивает итог сверху. Fraud с весом 100 обнуляет
вкладовый блок, но не общий блок.

### 13.3. Количество отклонений

```text
deviations_count = число score=0 среди включённых критериев
```

При `DEPOSIT_TOPIC=0` вкладовые нули сюда не входят.

## 14. Готовая карточка одного звонка

После scoring вызывается
[`build_dialog_report()`](analyzer/app/services/dialog_report_builder.py).

Она не обращается к LLM. Из готовых критериев выбираются:

- топ успешных метрик;
- топ нарушений;
- recommendation из YAML;
- quote из ответа LLM.

Сортировка идёт по severity, затем по штрафу, затем по code.

Положительный текст выбирается детерминированно по SHA-256 от `call_id` из
[`positive_templates.yaml`](analyzer/app/agents/prompts/positive_templates.yaml).
Один и тот же звонок всегда получает один и тот же шаблон.

Пример `dialog_report`:

```json
{
  "callId": "call-deposit-001",
  "clientFio": "Иванов Иван Иванович",
  "occurredAt": "2026-10-26T10:15:00+00:00",
  "type": "call",
  "score": 82.5,
  "deviationsCount": 2,
  "strengths": {
    "text": "Вы хорошо выполнили следующие критерии: приветствие, представление.",
    "metrics": [
      {"code": "GENERAL_01", "title": "Приветствие"}
    ]
  },
  "improvements": [
    {
      "code": "DEPOSIT_04",
      "title": "Согласование следующего шага",
      "severity": "critical",
      "recommendation": "Согласуйте с клиентом следующий шаг.",
      "quote": "Я тогда подумаю"
    }
  ]
}
```

## 15. Финальная транзакция анализа

Оркестратор вызывает:

```python
await repository.complete_analysis(
    call_id=call_id,
    analysis_results=results,
    q_score=q_score,
    critical_violation=critical_violation,
    criteria=criteria,
    dialog_report=dialog_report,
    general_score=general_score,
    deposit_topic=deposit_topic,
    deposit_score=deposit_score,
    deviations_count=deviations_count,
)
```

В одной транзакции:

1. блокируется строка `dialogs`;
2. сохраняются все итоговые поля;
3. статус становится `completed`;
4. старые строки критериев этого звонка удаляются;
5. записываются новые `dialog_metric_results`.

`analyzer.dialog_metric_results` содержит по одной строке на критерий:

| Поле | Значение |
|---|---|
| `call_id` | связь со звонком |
| `manager_id`, `client_epk` | связь с менеджером и клиентом |
| `metric_code`, `metric_title` | идентификатор и название |
| `metric_block` | `general` либо `deposit` |
| `score` | `0` или `1` |
| `severity`, `penalty` | серверные метаданные |
| `quote` | цитата нарушения |
| `recommendation` | текст из YAML |
| `included_in_analytics` | можно ли учитывать строку в витринах |
| `occurred_at` | время коммуникации |

После коммита задача получает `analysis_tasks.status=completed`.

## 16. Ошибка анализа

Любая ошибка внутри task перехватывается на границе
`AnalysisWorker._process()`.

Worker выполняет:

```text
analysis_tasks.status = failed
analysis_tasks.error_code = имя исключения
analysis_tasks.attempt_count = число попыток LLM

dialogs.analysis_status = failed
dialogs.error_code = имя исключения
```

После этого worker не падает и переходит к следующим задачам.

Failed-звонок не возвращается публичным GET, потому что
`DialogRepository.get_completed()` явно требует:

```sql
analysis_status = 'completed'
```

Ручной повтор можно поставить через:

```http
POST /analysis/run/dialog
```

```json
{
  "call_id": "call-deposit-001",
  "manager_id": "00000001"
}
```

Task остаётся идемпотентным в рамках `report_version`.

## 17. Ежедневная сборка dashboard

Анализ звонка заканчивается сразу после сохранения `completed`. Основные блоки
страницы готовятся отдельно через
[`DashboardBuilder`](analyzer/app/services/dashboard_builder.py).

[`DashboardScheduler`](analyzer/app/services/dashboard_scheduler.py) запускает
сборку по расписанию:

```env
DASHBOARD_ENABLED=true
DASHBOARD_CRON_HOUR_UTC=18
```

Можно вызвать вручную:

```http
POST /analysis/run/dashboard?date=2026-10-25
```

Во время `rebuild(snapshot_date)`:

1. берутся менеджеры из `ANALYZED_MANAGER_IDS`;
2. читаются только `completed` диалоги;
3. рассчитывается Q-score текущего квартала;
4. считается медиана личных результатов всех менеджеров;
5. строится 30-дневное скользящее окно метрик;
6. строится предыдущее окно, сдвинутое на один день;
7. выбираются риски, strengths и improvements;
8. собираются четыре недельные точки;
9. сохраняются готовые JSON snapshots.

LLM при сборке dashboard не вызывается.

## 18. Как строятся восемь блоков

### 18.1. Q-score

Период: от начала текущего квартала до `snapshot_date`.

Возвращаются:

- средняя личная оценка;
- медиана личных оценок всех анализируемых менеджеров;
- количество коммуникаций;
- доля звонков с оценкой `0–40`;
- оценки трёх месяцев квартала, включая `0` при отсутствии данных.

### 18.2. Клиенты в зоне риска

Берутся нарушения за последние 30 дней. Группировка:

```text
client_epk + metric_code
```

Для одного клиента выбирается одна метрика. Приоритет:

1. fraud;
2. critical;
3. significant;
4. minor;
5. info;
6. более свежее нарушение;
7. больше повторений;
8. стабильная сортировка по code.

Основной блок содержит максимум `RISK_CLIENTS_LIMIT`, по умолчанию четыре
клиента.

### 18.3. Что получается отлично

Для каждой включённой метрики:

```text
current_percent = сумма score / количество коммуникаций × 100
```

В strengths попадают метрики с результатом не ниже
`STRENGTH_MIN_PERCENT=80`. Выводится топ-3.

### 18.4. Что нужно улучшить

Метрики ниже 80% попадают в improvements. Сортировка сначала учитывает
критичность, затем худший процент и количество проверенных коммуникаций.

### 18.5. Последние коммуникации

Берутся последние `LATEST_COMMUNICATIONS_LIMIT=5` завершённых звонков за всю
доступную историю менеджера.

### 18.6. Popup клиента и метрики

Готовый snapshot содержит клиента, нарушение, количество повторений, последний
звонок, цитату и рекомендацию.

### 18.7. Popup метрики

Для выбранной метрики сохраняются:

- current/previous percent и delta;
- четыре завершённые календарные недели;
- максимум три последних звонка со `score=0`;
- клиент, время и цитата каждого звонка.

### 18.8. Полный отчёт одного звонка

Берётся готовый `dialogs.dialog_report`. Никаких повторных вычислений и LLM.

## 19. Таблицы готовых витрин

### `manager_dashboard_snapshots`

Одна строка на менеджера и дату. `payload` уже содержит пять основных блоков:

```text
qScore
clientsAtRisk
strengths
improvements
communications
```

### `client_metric_snapshots`

Детализация связки:

```text
manager_id + client_epk + metric_code + snapshot_date
```

### `manager_metric_snapshots`

Детализация метрики менеджера:

```text
manager_id + metric_code + snapshot_date
```

GET читает последнюю доступную дату. Поэтому на каждый пользовательский запрос
не выполняются тяжёлые группировки по `dialog_metric_results`.

## 20. Восемь публичных GET

Routes:
[`analyzer/app/api/manager.py`](analyzer/app/api/manager.py).

| № | Endpoint | Источник |
|---:|---|---|
| 1 | `GET /manager/{manager_id}/q-score` | `manager_dashboard_snapshots.payload.qScore` |
| 2 | `GET /manager/{manager_id}/clients-at-risk` | `payload.clientsAtRisk` |
| 3 | `GET /manager/{manager_id}/strengths` | `payload.strengths` |
| 4 | `GET /manager/{manager_id}/improvements` | `payload.improvements` |
| 5 | `GET /manager/{manager_id}/communications` | `payload.communications` |
| 6 | `GET /manager/{manager_id}/clients/{client_epk}/metrics/{metric_code}` | `client_metric_snapshots` |
| 7 | `GET /manager/{manager_id}/metrics/{metric_code}` | `manager_metric_snapshots` |
| 8 | `GET /manager/dialogs/{call_id}` | `dialogs.dialog_report` |

Цепочка обычного GET:

```text
FastAPI router
    → ManagerService
        → DashboardRepository/DialogRepository
            → один короткий SELECT
                → готовый JSON
```

Если snapshot либо completed-отчёт отсутствует, API возвращает `404`.
`waiting`, `processing` и `failed` наружу не показываются.

## 21. Полный пример A: разговор про вклад

Исходные данные:

```text
call_id          = call-deposit-001
manager_id       = 00000001
client_epk       = epk-ivanov-001
client_fio       = Иванов Иван Иванович
duration_seconds = 84
cleaned_text     = разговор об открытии вклада
```

### Шаг 1. Callback

`cleaned_dialog(payload, request)` получает Pydantic-объект в памяти и вызывает
`DialogIntakeService.accept(payload)`.

### Шаг 2. Фильтры

```text
84 >= 50                         → дальше
рабочая дата существует         → дальше
00000001 входит в manager set   → дальше
required_analyzers=(prompt,)     → дальше
```

### Шаг 3. База

Создаются:

```text
dialogs[call-deposit-001]       status=waiting
analysis_tasks[...]             status=waiting
```

Callback возвращает `202`. В памяти HTTP-handler больше ничего не держит.

### Шаг 4. Worker

Через максимум `WORKER_POLL_INTERVAL_SECONDS` task забирается через
`FOR UPDATE SKIP LOCKED` и становится `processing`.

### Шаг 5. Общий LLM-запрос

В памяти создаются system/user prompts блока `general`. Provider ждёт общий
GigaChat semaphore и отправляет запрос. Допустим, ответ:

```json
{
  "results": [
    {"code": "GENERAL_01", "score": 1, "quote": null},
    {"code": "GENERAL_03", "score": 0, "quote": "Я не буду это объяснять"}
  ]
}
```

### Шаг 6. Вкладовый LLM-запрос

Тот же текст отправляется с каталогом `deposit`:

```json
{
  "results": [
    {"code": "DEPOSIT_TOPIC", "score": 1, "quote": null},
    {"code": "DEPOSIT_01", "score": 1, "quote": null},
    {"code": "DEPOSIT_04", "score": 0, "quote": "Я тогда подумаю"}
  ]
}
```

### Шаг 7. Python scoring

Допустим:

```text
general_score = 90
deposit_score = 75
final_score   = (90 + 75) / 2 = 82.5
deposit_topic = true
```

Оба блока входят в аналитику.

### Шаг 8. Финальная запись

`dialogs` обновляется до `completed`; создаются строки общих и вкладовых
метрик; готовая карточка сохраняется в `dialog_report`.

### Шаг 9. Dashboard

При следующем rebuild звонок участвует:

- в квартальном Q-score;
- в 30-дневных процентах;
- в зоне риска;
- в strengths/improvements;
- в последних коммуникациях.

## 22. Полный пример B: разговор не про вклад

Исходные данные:

```text
call_id          = call-card-002
manager_id       = 00000002
client_epk       = epk-petrov-002
client_fio       = Петров Пётр Петрович
duration_seconds = 66
cleaned_text     = разговор о банковской карте
```

Фильтры и первый общий запрос проходят так же.

Второй LLM-запрос выполняется обязательно и может вернуть:

```json
{
  "results": [
    {"code": "DEPOSIT_TOPIC", "score": 0, "quote": null},
    {"code": "DEPOSIT_01", "score": 1, "quote": null},
    {"code": "DEPOSIT_04", "score": 0, "quote": null}
  ]
}
```

Python смотрит только на gate:

```text
DEPOSIT_TOPIC=0
```

После этого результат нормализуется:

```text
все deposit score             = 0
included_in_analytics         = false
deposit_score                 = null
deviations_count              = только general violations
final_score                   = general_score
```

`DEPOSIT_04=0` не станет недостатком менеджера, не попадёт в клиентский риск и
не испортит процент выполнения. На фронте вкладовый блок этого звонка не
появится.

## 23. Что находится в памяти и что в БД

| Момент | Оперативная память | PostgreSQL |
|---|---|---|
| callback | Pydantic `CleanedDialog` | пока ничего |
| после фильтров | payload + `work_date` + profile | `dialogs=waiting` |
| после enqueue | текущий HTTP handler | `analysis_tasks=waiting` |
| claim worker-а | список `AnalysisTaskEntity` | task/dialog `processing` |
| general request | prompts + LLM response | исходный dialog остаётся |
| deposit request | prompts + LLM response | исходный dialog остаётся |
| scoring | два ответа + metadata + score | пока старый status |
| complete | итоговый payload до commit | dialog/metrics `completed` |
| dashboard rebuild | выборка completed facts | snapshots |
| GET | один готовый JSON | только SELECT |

Большие промежуточные prompts и HTTP-ответы LLM в отдельных таблицах не
хранятся. В БД сохраняется нормализованный итог.

## 24. Основные ENV-настройки

### Вход и worker

```env
MIN_DIALOG_DURATION_SECONDS=50
CALENDAR_FILTER_ENABLED=true
WORKER_POLL_INTERVAL_SECONDS=30
WORKER_CLAIM_LIMIT=100
DIALOG_PIPELINE_CONCURRENCY=10
```

### Менеджеры

```env
ANALYZED_MANAGER_IDS=00000001,00000002
PROMPT_ANALYZER_MANAGER_IDS=00000001,00000002
AUDIO_ANALYZER_MANAGER_IDS=
FAQ_ANALYZER_MANAGER_IDS=
```

### GigaChat

```env
LLM_PROVIDER=gigachat
GIGACHAT_MODEL=GigaChat-2-Pro
GIGACHAT_MAX_CONCURRENCY=1
GIGACHAT_MAX_ATTEMPTS=5
GIGACHAT_RETRY_BASE_SECONDS=1
GIGACHAT_TIMEOUT_SECONDS=120
GIGACHAT_TEMPERATURE=0.1
GIGACHAT_MAX_OUTPUT_TOKENS=8000
GIGACHAT_MAX_INPUT_TOKENS=116000
LOG_LLM_RESPONSES=true
```

### Бизнес-настройки dashboard

```env
DEPOSIT_ANALYSIS_ENABLED=true
CRITICAL_SCORE_CAP=80
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
EMPTY_SCORE_VALUE=0
```

Полный набор находится в [`.env.example`](.env.example) и
[`analyzer/.env.example`](analyzer/.env.example).

## 25. Какие логи ожидать

Успешный путь:

```text
Dialog callback received call_id=call-deposit-001
Dialog saved call_id=call-deposit-001
Dialog task created call_id=call-deposit-001
Tasks claimed count=1 limit=10
Task started type=dialog key=call-deposit-001
Dialog analysis started call_id=call-deposit-001
Agent started call_id=call-deposit-001 name=prompt
LLM response body=...
LLM response body=...
Agent response received call_id=call-deposit-001 name=prompt
Dialog result saved call_id=call-deposit-001
Task completed type=dialog key=call-deposit-001
```

GET:

```text
Dialog GET received call_id=call-deposit-001
Dialog GET returned call_id=call-deposit-001 score=82.5 criteria=2
```

Если после callback нет `Dialog saved`, смотрим входные фильтры. Если есть task,
но нет `Task started`, смотрим `analysis_tasks` и worker. Если есть `Agent
started`, но нет ответа, смотрим provider, semaphore, timeout и retries.

## 26. Быстрый локальный запуск

Из корня проекта:

```bash
cp .env.example .env
docker compose up -d --build
docker compose logs -f analyzer
```

Swagger:

```text
Kafka Producer: http://localhost:8083/docs
Analyzer:       http://localhost:8082/docs
Data Cleaner:   http://localhost:8081/docs
```

PostgreSQL с хоста:

```text
host:     127.0.0.1
port:     значение опубликованного порта из docker compose
database: quality
user:     quality
password: quality
```

Полезные SQL-запросы:

```sql
SELECT call_id, manager_id, analysis_status, q_score, deposit_topic
FROM analyzer.dialogs
ORDER BY created_at DESC;

SELECT task_type, entity_key, status, attempt_count, error_code
FROM analyzer.analysis_tasks
ORDER BY created_at DESC;

SELECT call_id, metric_code, score, severity, included_in_analytics
FROM analyzer.dialog_metric_results
ORDER BY occurred_at DESC, metric_code;

SELECT manager_id, snapshot_date, payload
FROM analyzer.manager_dashboard_snapshots
ORDER BY snapshot_date DESC;
```

## 27. Что сейчас намеренно не участвует в основном pipeline

- старые daily/weekly/four-week/quarterly LLM-отчёты;
- Audio Analyzer без заданного URL и manager profile;
- FAQ/IDP Analyzer без заданного URL и manager profile;
- сложные вычисления во время GET;
- повторный LLM-запрос для положительной суммаризации;
- клиентские риски из неактуального вкладового блока;
- звонки короче 50 секунд и отфильтрованные менеджеры.

Главный рабочий контур сейчас: два LLM-запроса на звонок, детерминированный
Python scoring, сохранённый отчёт звонка и заранее подготовленные read-модели
восьми интерфейсных блоков.
