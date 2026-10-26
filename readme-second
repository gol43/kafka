# Короткий E2E Analyzer

Это рабочая шпаргалка для запуска проекта на другом ноутбуке. Подробная
архитектура находится в [`README.md`](README.md). Здесь только последовательный
сценарий: что запустить, что отправить и где посмотреть результат.

## 1. Что мы проверяем

```text
готовый объект Data Cleaner
    ↓ POST /internal/v1/dialogs/cleaned
входные фильтры Analyzer
    ↓
dialogs=waiting + analysis_tasks=waiting
    ↓ worker
два LLM-запроса
    ↓
Python рассчитывает score
    ↓
dialogs=completed + dialog_metric_results
    ↓ ручная сборка dashboard
готовые GET для фронтенда
```

Для этого теста Kafka, Kafka Consumer и Data Cleaner запускать не обязательно.
Мы отправим в Analyzer ровно тот JSON, который в нормальной схеме должен
прислать Data Cleaner.

## 2. Забираем проект с GitHub

```powershell
git clone https://github.com/gol43/kafka.git
cd kafka
Copy-Item .env.example .env
```

Для Git Bash последняя команда выглядит так:

```bash
cp .env.example .env
```

## 3. Минимальные настройки

Для локального теста в `.env` должны остаться:

```env
POSTGRES_DB=quality
POSTGRES_USER=quality
POSTGRES_PASSWORD=quality
POSTGRES_HOST_PORT=55432

LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen3:4b-instruct
ACTIVE_CRITERIA_CODES=GENERAL_01,GENERAL_02,GENERAL_03

ANALYZED_MANAGER_IDS=00000001,00000002
PROMPT_ANALYZER_MANAGER_IDS=00000001,00000002
AUDIO_ANALYZER_MANAGER_IDS=
FAQ_ANALYZER_MANAGER_IDS=

CALENDAR_FILTER_ENABLED=false
MIN_DIALOG_DURATION_SECONDS=50
WORKER_POLL_INTERVAL_SECONDS=30
DIALOG_PIPELINE_CONCURRENCY=10
GIGACHAT_MAX_CONCURRENCY=1
GIGACHAT_MAX_ATTEMPTS=5
DEPOSIT_ANALYSIS_ENABLED=true
```

Почему здесь остаются настройки `GIGACHAT_*`, хотя используется Ollama:
оба provider-а используют общие настройки timeout, semaphore, attempts и
ограничений токенов.

Текущий [`docker-compose.yml`](docker-compose.yml) явно задаёт Analyzer-у
`LLM_PROVIDER: ollama`. Поэтому обычный локальный Compose всегда использует
бесплатную локальную модель.

Для корпоративного GigaChat нужно поменять это значение в сервисе `analyzer`
на `gigachat` и заполнить:

```env
GIGACHAT_CREDENTIALS=...
GIGACHAT_SCOPE=GIGACHAT_API_CORP
GIGACHAT_MODEL=GigaChat-2-Pro
GIGACHAT_VERIFY_SSL=true
GIGACHAT_CERT_FILE=...
GIGACHAT_KEY_FILE=...
```

Секреты в Git не добавляем.

## 4. Запускаем только необходимое

```powershell
docker compose up -d --build postgres ollama ollama-pull analyzer
```

Первый запуск будет дольше обычного: `ollama-pull` скачивает модель.

Состояние контейнеров:

```powershell
docker compose ps -a
```

Нужно получить:

```text
postgres      healthy
ollama        healthy
ollama-pull   exited (0)
analyzer      healthy
```

Логи Analyzer:

```powershell
docker compose logs -f analyzer
```

Swagger:

```text
http://localhost:8082/docs
```

## 5. Какие данные ждёт Analyzer

Входной контракт описан в
[`analyzer/app/schemas/dialogs.py`](analyzer/app/schemas/dialogs.py).

Основные поля:

| Поле | Что передать |
|---|---|
| `call_id` | уникальный ID звонка |
| `manager_id` | ровно восемь цифр |
| `manager_name` | имя менеджера |
| `client_epk` | ID клиента |
| `client_fio` | ФИО клиента |
| `duration_seconds` | минимум 50 секунд |
| `occurred_at` | дата и время звонка |
| `cleaned_text` | цельный обезличенный диалог |
| `utterances` | реплики, роли и тайм-коды |
| `encrypted` | для Analyzer всегда `false` |

Готовые примеры:

- [`examples/cleaned-dialog-deposit.json`](examples/cleaned-dialog-deposit.json) — разговор про вклад;
- [`examples/cleaned-dialog-non-deposit.json`](examples/cleaned-dialog-non-deposit.json) — разговор про карту.

## 6. Отправляем два callback

PowerShell и Git Bash могут выполнить одинаковые команды через `curl.exe`:

```powershell
curl.exe -X POST "http://localhost:8082/internal/v1/dialogs/cleaned" `
  -H "Content-Type: application/json" `
  --data-binary "@examples/cleaned-dialog-deposit.json"
```

```powershell
curl.exe -X POST "http://localhost:8082/internal/v1/dialogs/cleaned" `
  -H "Content-Type: application/json" `
  --data-binary "@examples/cleaned-dialog-non-deposit.json"
```

В Git Bash команды должны быть в одну строку либо с `\`:

```bash
curl -X POST "http://localhost:8082/internal/v1/dialogs/cleaned" \
  -H "Content-Type: application/json" \
  --data-binary "@examples/cleaned-dialog-deposit.json"

curl -X POST "http://localhost:8082/internal/v1/dialogs/cleaned" \
  -H "Content-Type: application/json" \
  --data-binary "@examples/cleaned-dialog-non-deposit.json"
```

Оба запроса должны вернуть HTTP `202`.

Самостоятельно вставлять `waiting` через SQL не нужно. Callback вызывает
[`DialogIntakeService.accept()`](analyzer/app/services/dialog_intake.py), и тот
сам создаёт:

```text
analyzer.dialogs.analysis_status       = waiting
analyzer.analysis_tasks.status         = waiting
```

## 7. Сразу смотрим, что сохранилось

Открыть `psql` внутри Docker:

```powershell
docker compose run --rm --no-deps -e PGPASSWORD=quality postgres `
  psql -h postgres -p 5432 -U quality -d quality
```

Для Git Bash та же команда пишется в одну строку:

```bash
docker compose run --rm --no-deps -e PGPASSWORD=quality postgres psql -h postgres -p 5432 -U quality -d quality
```

Диалоги:

```sql
SELECT
    call_id,
    manager_id,
    client_epk,
    duration_seconds,
    analysis_status,
    q_score,
    deposit_topic,
    error_code
FROM analyzer.dialogs
WHERE call_id IN (
    'work-e2e-deposit-001',
    'work-e2e-card-002'
)
ORDER BY call_id;
```

Очередь worker-а:

```sql
SELECT
    task_type,
    entity_key,
    status,
    attempt_count,
    error_code,
    created_at,
    updated_at
FROM analyzer.analysis_tasks
WHERE entity_key IN (
    'work-e2e-deposit-001',
    'work-e2e-card-002'
)
ORDER BY created_at;
```

Сразу после callback статус может быть `waiting`. Когда worker заберёт задачу,
он станет `processing`. Успешный финал — `completed`.

Выход из `psql`:

```text
\q
```

## 8. Что происходит после waiting

Worker каждые 30 секунд вызывает
[`AnalysisTaskRepository.claim()`](analyzer/app/database/repositories/analysis_task_repository.py).

Он забирает task через `FOR UPDATE SKIP LOCKED`, ставит `processing` и вызывает:

```python
await dialog_orchestrator.process(call_id)
```

Для каждого диалога выполняются два последовательных LLM-запроса:

```python
await agent.analyze(cleaned_text, "general")
await agent.analyze(cleaned_text, "deposit")
```

При `GIGACHAT_MAX_CONCURRENCY=1` наружу идёт только один LLM-запрос за раз.
Поэтому два диалога могут обрабатываться параллельно внутри worker-а, но их
реальные запросы к модели будут проходить по одному.

В логах ожидаем:

```text
Dialog callback received call_id=...
Dialog saved call_id=...
Dialog task created call_id=...
Tasks claimed count=...
Task started type=dialog key=...
Dialog analysis started call_id=...
Agent started call_id=... name=prompt
LLM response body=...
LLM response body=...
Agent response received call_id=... name=prompt
Dialog result saved call_id=...
Task completed type=dialog key=...
```

## 9. Проверяем результаты критериев

После `completed`:

```sql
SELECT
    call_id,
    metric_block,
    metric_code,
    score,
    severity,
    penalty,
    included_in_analytics,
    quote
FROM analyzer.dialog_metric_results
WHERE call_id IN (
    'work-e2e-deposit-001',
    'work-e2e-card-002'
)
ORDER BY call_id, metric_block, metric_code;
```

Ожидаемая разница:

```text
work-e2e-deposit-001
    deposit_topic=true
    общие и вкладовые метрики включены в аналитику
    final score строится из general и deposit score

work-e2e-card-002
    deposit_topic=false
    вкладовые score сохраняются как 0
    included_in_analytics=false для вкладовых метрик
    final score равен general score
```

Точный набор нулей и единиц зависит от ответа модели. Важна именно ветка
`deposit_topic`.

## 10. Получаем карточки звонков

```powershell
curl.exe "http://localhost:8082/manager/dialogs/work-e2e-deposit-001"
curl.exe "http://localhost:8082/manager/dialogs/work-e2e-card-002"
```

До `completed` ручка возвращает `404`. После завершения ожидается готовый JSON:

```json
{
  "callId": "work-e2e-deposit-001",
  "clientFio": "Иванов Иван Иванович",
  "occurredAt": "2026-10-27T09:15:00+00:00",
  "type": "call",
  "score": 82.5,
  "deviationsCount": 2,
  "strengths": {
    "text": "...",
    "metrics": []
  },
  "improvements": []
}
```

## 11. Собираем dashboard вручную

Автоматический scheduler работает по времени. Для E2E ждать его не надо:

```powershell
curl.exe -X POST "http://localhost:8082/analysis/run/dashboard?date=2026-10-27"
```

Дата должна быть не раньше `occurred_at` тестовых звонков.

Проверяем snapshot:

```sql
SELECT
    manager_id,
    snapshot_date,
    payload
FROM analyzer.manager_dashboard_snapshots
WHERE manager_id IN ('00000001', '00000002')
ORDER BY manager_id, snapshot_date DESC;
```

## 12. Вызываем восемь GET

Основные блоки менеджера:

```powershell
curl.exe "http://localhost:8082/manager/00000001/q-score"
curl.exe "http://localhost:8082/manager/00000001/clients-at-risk"
curl.exe "http://localhost:8082/manager/00000001/strengths"
curl.exe "http://localhost:8082/manager/00000001/improvements"
curl.exe "http://localhost:8082/manager/00000001/communications"
```

Детализация клиента и метрики требует реальные `client_epk` и `metric_code` из
полученного snapshot:

```powershell
curl.exe "http://localhost:8082/manager/00000001/clients/epk-ivanov-001/metrics/DEPOSIT_04"
curl.exe "http://localhost:8082/manager/00000001/metrics/DEPOSIT_04"
```

Карточка звонка:

```powershell
curl.exe "http://localhost:8082/manager/dialogs/work-e2e-deposit-001"
```

Если конкретный metric не попал в risk/improvements, его detail snapshot не
создастся и соответствующий GET вернёт `404`. Возьми фактический `metricCode`
из `/clients-at-risk` либо `/improvements`.

## 13. Где искать проблему

### Callback вернул 422

Проверить:

- `manager_id` состоит ровно из восьми цифр;
- `manager_name`, `client_epk`, `cleaned_text` не пустые;
- `encrypted=false`;
- JSON соответствует `CleanedDialog`.

### Callback вернул 202, но строки dialogs нет

Проверить логи:

```text
Dialog too short
Dialog skipped by calendar
Dialog manager skipped
```

### Dialog остаётся waiting

```powershell
docker compose logs --tail 200 analyzer
```

И SQL:

```sql
SELECT *
FROM analyzer.analysis_tasks
WHERE entity_key = 'work-e2e-deposit-001';
```

### Task стал failed

Смотреть `error_code`, полный лог Analyzer и ответы LLM:

```sql
SELECT entity_key, status, attempt_count, error_code
FROM analyzer.analysis_tasks
WHERE status = 'failed';
```

При локальной Ollama дополнительно:

```powershell
docker compose logs --tail 200 ollama
docker compose ps -a ollama-pull
```

### Dialog completed, но dashboard GET даёт 404

Нужно вручную вызвать `/analysis/run/dashboard?date=...` и убедиться, что дата
snapshot включает время тестового звонка.

## 14. Самый короткий сценарий

```powershell
git clone https://github.com/gol43/kafka.git
cd kafka
Copy-Item .env.example .env
docker compose up -d --build postgres ollama ollama-pull analyzer

curl.exe -X POST "http://localhost:8082/internal/v1/dialogs/cleaned" -H "Content-Type: application/json" --data-binary "@examples/cleaned-dialog-deposit.json"
curl.exe -X POST "http://localhost:8082/internal/v1/dialogs/cleaned" -H "Content-Type: application/json" --data-binary "@examples/cleaned-dialog-non-deposit.json"

docker compose logs -f analyzer

curl.exe "http://localhost:8082/manager/dialogs/work-e2e-deposit-001"
curl.exe "http://localhost:8082/manager/dialogs/work-e2e-card-002"

curl.exe -X POST "http://localhost:8082/analysis/run/dashboard?date=2026-10-27"
curl.exe "http://localhost:8082/manager/00000001/q-score"
curl.exe "http://localhost:8082/manager/00000001/communications"
```

Этого достаточно, чтобы без Kafka и Data Cleaner проверить полный рабочий путь
Analyzer: входной контракт, фильтры, очередь, worker, два LLM-запроса, score,
PostgreSQL, карточку звонка и dashboard.

## 15. Два готовых curl со всем JSON внутри

Ниже не нужны файлы из `examples/`. Запусти сервисы, скопируй первую команду
целиком в PowerShell, затем вторую. Каждый callback сам создаст строку
`dialogs=waiting`, задание `analysis_tasks=waiting` и запустит весь анализ через
worker.

### Разговор про вклад

```powershell
curl.exe -X POST "http://localhost:8082/internal/v1/dialogs/cleaned" -H "Content-Type: application/json" --data-raw '{"contract_version":"1.0","cleaner_version":"manual-e2e-1","call_id":"work-e2e-deposit-001","manager_id":"00000001","manager_name":"Анна Смирнова","client_epk":"epk-ivanov-001","client_fio":"Иванов Иван Иванович","duration_seconds":78,"occurred_at":"2026-10-27T09:15:00Z","channel":"phone","participants":[{"role":"employee","name":"Анна Смирнова","employee_id":"00000001"},{"role":"client","name":"Иванов Иван Иванович"}],"cleaned_text":"Сотрудник: Добрый день! Меня зовут Анна, Сбербанк. Чем могу помочь? Клиент: Хочу открыть вклад на шесть месяцев. Сотрудник: Подскажите, какую сумму вы планируете разместить? Клиент: Пятьсот тысяч рублей. Сотрудник: Для этой суммы подходит вклад с фиксированной ставкой. Проценты начисляются ежемесячно. Клиент: Хорошо, я подумаю. Сотрудник: Я не согласовала с вами следующий шаг. Спасибо за звонок, до свидания.","utterances":[{"sequence_number":0,"speaker_role":"employee","speaker_id":1,"channel":1,"text":"Добрый день! Меня зовут Анна, Сбербанк. Чем могу помочь?","normalized_text":"Добрый день! Меня зовут Анна, Сбербанк. Чем могу помочь?","start_ms":0,"end_ms":9000,"emotions":{"positive":0.7,"neutral":0.3,"negative":0.0},"word_alignments":[]},{"sequence_number":1,"speaker_role":"client","speaker_id":2,"channel":2,"text":"Хочу открыть вклад на шесть месяцев.","normalized_text":"Хочу открыть вклад на шесть месяцев.","start_ms":10000,"end_ms":18000,"emotions":{"positive":0.2,"neutral":0.8,"negative":0.0},"word_alignments":[]},{"sequence_number":2,"speaker_role":"employee","speaker_id":1,"channel":1,"text":"Подскажите, какую сумму вы планируете разместить?","normalized_text":"Подскажите, какую сумму вы планируете разместить?","start_ms":19000,"end_ms":28000,"emotions":null,"word_alignments":[]},{"sequence_number":3,"speaker_role":"client","speaker_id":2,"channel":2,"text":"Пятьсот тысяч рублей.","normalized_text":"Пятьсот тысяч рублей.","start_ms":29000,"end_ms":35000,"emotions":null,"word_alignments":[]},{"sequence_number":4,"speaker_role":"employee","speaker_id":1,"channel":1,"text":"Для этой суммы подходит вклад с фиксированной ставкой. Проценты начисляются ежемесячно.","normalized_text":"Для этой суммы подходит вклад с фиксированной ставкой. Проценты начисляются ежемесячно.","start_ms":36000,"end_ms":56000,"emotions":null,"word_alignments":[]},{"sequence_number":5,"speaker_role":"client","speaker_id":2,"channel":2,"text":"Хорошо, я подумаю.","normalized_text":"Хорошо, я подумаю.","start_ms":57000,"end_ms":63000,"emotions":null,"word_alignments":[]},{"sequence_number":6,"speaker_role":"employee","speaker_id":1,"channel":1,"text":"Я не согласовала с вами следующий шаг. Спасибо за звонок, до свидания.","normalized_text":"Я не согласовала с вами следующий шаг. Спасибо за звонок, до свидания.","start_ms":64000,"end_ms":78000,"emotions":null,"word_alignments":[]}],"source_metadata":{"source":"manual-work-e2e"},"encrypted":false}'
```

### Разговор не про вклад

```powershell
curl.exe -X POST "http://localhost:8082/internal/v1/dialogs/cleaned" -H "Content-Type: application/json" --data-raw '{"contract_version":"1.0","cleaner_version":"manual-e2e-1","call_id":"work-e2e-card-002","manager_id":"00000002","manager_name":"Олег Петров","client_epk":"epk-petrov-002","client_fio":"Петров Пётр Петрович","duration_seconds":69,"occurred_at":"2026-10-27T10:30:00Z","channel":"phone","participants":[{"role":"employee","name":"Олег Петров","employee_id":"00000002"},{"role":"client","name":"Петров Пётр Петрович"}],"cleaned_text":"Сотрудник: Добрый день! Меня зовут Олег, Сбербанк. Чем могу помочь? Клиент: У меня закончился срок действия банковской карты. Сотрудник: Я проверю доступные способы перевыпуска. Новую карту можно получить в выбранном офисе. Клиент: Когда она будет готова? Сотрудник: Обычно выпуск занимает несколько рабочих дней. Я направлю уведомление, когда карта поступит в офис. Клиент: Спасибо. Сотрудник: Благодарю за обращение. До свидания.","utterances":[{"sequence_number":0,"speaker_role":"employee","speaker_id":1,"channel":1,"text":"Добрый день! Меня зовут Олег, Сбербанк. Чем могу помочь?","normalized_text":"Добрый день! Меня зовут Олег, Сбербанк. Чем могу помочь?","start_ms":0,"end_ms":9000,"emotions":{"positive":0.6,"neutral":0.4,"negative":0.0},"word_alignments":[]},{"sequence_number":1,"speaker_role":"client","speaker_id":2,"channel":2,"text":"У меня закончился срок действия банковской карты.","normalized_text":"У меня закончился срок действия банковской карты.","start_ms":10000,"end_ms":19000,"emotions":null,"word_alignments":[]},{"sequence_number":2,"speaker_role":"employee","speaker_id":1,"channel":1,"text":"Я проверю доступные способы перевыпуска. Новую карту можно получить в выбранном офисе.","normalized_text":"Я проверю доступные способы перевыпуска. Новую карту можно получить в выбранном офисе.","start_ms":20000,"end_ms":37000,"emotions":null,"word_alignments":[]},{"sequence_number":3,"speaker_role":"client","speaker_id":2,"channel":2,"text":"Когда она будет готова?","normalized_text":"Когда она будет готова?","start_ms":38000,"end_ms":44000,"emotions":null,"word_alignments":[]},{"sequence_number":4,"speaker_role":"employee","speaker_id":1,"channel":1,"text":"Обычно выпуск занимает несколько рабочих дней. Я направлю уведомление, когда карта поступит в офис.","normalized_text":"Обычно выпуск занимает несколько рабочих дней. Я направлю уведомление, когда карта поступит в офис.","start_ms":45000,"end_ms":61000,"emotions":null,"word_alignments":[]},{"sequence_number":5,"speaker_role":"client","speaker_id":2,"channel":2,"text":"Спасибо.","normalized_text":"Спасибо.","start_ms":62000,"end_ms":64000,"emotions":null,"word_alignments":[]},{"sequence_number":6,"speaker_role":"employee","speaker_id":1,"channel":1,"text":"Благодарю за обращение. До свидания.","normalized_text":"Благодарю за обращение. До свидания.","start_ms":65000,"end_ms":69000,"emotions":null,"word_alignments":[]}],"source_metadata":{"source":"manual-work-e2e"},"encrypted":false}'
```

Эти две команды запускают полный pipeline анализа звонков. Дождись в логах двух
строк `Task completed`, после чего карточки доступны через GET:

```powershell
curl.exe "http://localhost:8082/manager/dialogs/work-e2e-deposit-001"
curl.exe "http://localhost:8082/manager/dialogs/work-e2e-card-002"
```

Dashboard строится отдельно от анализа звонка. Чтобы не ждать scheduler, после
завершения обеих задач выполни:

```powershell
curl.exe -X POST "http://localhost:8082/analysis/run/dashboard?date=2026-10-27"
```

После этого доступны основные блоки:

```powershell
curl.exe "http://localhost:8082/manager/00000001/q-score"
curl.exe "http://localhost:8082/manager/00000001/communications"
```

Если выполнить те же callback повторно с теми же `call_id`, новые строки не
создадутся: `call_id` и task сделаны идемпотентными. Для повторного чистого
прогона поменяй `call_id` либо пересоздай локальный volume PostgreSQL.
