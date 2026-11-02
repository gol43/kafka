# Analyzer: полное E2E-описание для аналитика и тестировщика

## 1. Назначение документа

Документ описывает текущее поведение микросервиса Analyzer в двух независимых
процессах:

1. анализ одного очищенного диалога;
2. ежедневное построение готовой dashboard-витрины.

Здесь зафиксированы:

- входные данные и проверки;
- календарные правила и граница `18:00 UTC`;
- состояния диалога и задания worker-а;
- три независимых LLM-анализа;
- детерминированная математика оценки;
- содержимое пяти таблиц PostgreSQL;
- окна 10 дней, 30 дней, недели, квартала и пяти месяцев;
- перенос предыдущего dashboard при отсутствии звонков;
- пакетные SQL-операции и ограничения памяти;
- формирование ответов восьми GET-ручек;
- назначение всех настроек Analyzer из ENV/ConfigMap.

Документ описывает код в каталоге `analyzer/app`. Kafka Consumer и Data Cleaner
считаются внешними системами: Analyzer получает от них уже очищенный и
нормализованный диалог.

---

## 2. Главная модель системы

В Analyzer нет отдельных дневных, недельных, месячных и квартальных LLM-отчётов.
Есть только два тяжёлых процесса:

```text
Процесс 1: один диалог
Data Cleaner → callback → фильтры → очередь → три LLM-запроса
→ Python scoring → готовый dialog_report

Процесс 2: dashboard
cron/manual run → cutoff очереди → пакетное чтение dialog_reports
→ дневная агрегация → окна и рейтинги → готовый dashboard_snapshot
```

LLM вызывается только в процессе анализа одного диалога. Dashboard строится
исключительно Python-кодом и SQL-запросами по уже готовым `dialog_reports` и
`dashboard_aggregates`.

---

## 3. Конфигурация при запуске

### 3.1. Когда читается конфигурация

`Settings` создаётся один раз при импорте приложения и кешируется через
`get_settings()`. В Kubernetes те же значения могут поступать из ConfigMap и
Secret как переменные окружения. Изменение ENV в работающем контейнере не
перестраивает конфигурацию: для применения изменений нужен перезапуск Analyzer.

При старте также один раз выполняется `PromptLoader`:

1. читает `dialog_system.md` и `dialog_user.md`;
2. читает YAML-критерии гигиены, вкладов и рисков;
3. накладывает `metric_metadata.yaml`;
4. валидирует уникальность кодов;
5. загружает варианты положительного текста из `positive_templates.yaml`;
6. формирует неизменяемые каталоги критериев по блокам.

Промпты не перечитываются перед каждым диалогом.

### 3.2. Проверки конфигурации

Приложение не стартует, если:

- менеджер назначен анализатору, но отсутствует в `ANALYZED_MANAGER_IDS`;
- для анализируемого менеджера не назначен ни один анализатор;
- у анализируемого менеджера нет обязательного Prompt Analyzer;
- включён Audio/Factor Analyzer, но не задан его URL;
- один табельный номер присутствует одновременно в двух ролевых списках;
- менеджер из `ANALYZED_MANAGER_IDS` отсутствует во всех четырёх ролях;
- одновременно заданы `GIGACHAT_TEMPERATURE` и `GIGACHAT_TOP_P`;
- risk-критерий в YAML имеет severity, отличный от `high`, `medium`, `low`;
- `ACTIVE_CRITERIA_CODES` содержит неизвестный код.

### 3.3. Четыре роли

Состав dashboard и командные показатели берутся только из четырёх ENV-set:

```env
EFS_VIP_KM_MANAGER_IDS=00000001,00000002
EFS_AKM_VIP_MANAGER_IDS=00000003
EFS_VIP_DSB_MANAGER_IDS=00000004
EFS_VIP_TFS_MANAGER_IDS=00000005
```

Значение можно передать строкой через запятую либо JSON-массивом. Табельный
номер нормализуется до восьми цифр.

Роль используется:

- при создании `dashboard_aggregates`;
- при создании `dashboard_snapshots`;
- для расчёта командной медианы Q-score.

Командный показатель никогда не смешивает менеджеров разных ролей.

---

# Часть I. E2E-анализ одного диалога

## 4. Вход от Data Cleaner

Analyzer принимает:

```http
POST /internal/v1/dialogs/cleaned
Content-Type: application/json
```

Ключевые поля запроса:

| Поле | Назначение |
|---|---|
| `call_id` | Уникальный идентификатор звонка |
| `manager_id` | Восьмизначный табельный номер |
| `client_epk` | Идентификатор клиента |
| `duration_seconds` | Длительность звонка |
| `occurred_at` | Время исходной коммуникации |
| `cleaned_text` | Очищенный текст с ролями сотрудника и клиента |
| `participants` | Участники разговора |
| `utterances` | Реплики, если Data Cleaner их передал |
| `source_metadata` | Дополнительные данные источника |

Для LLM используется только `cleaned_text`. Analyzer не хранит отдельную таблицу
реплик и не дублирует chunks.

HTTP `202 Accepted` означает только то, что callback обработан. Это не означает,
что LLM-анализ уже завершён.

## 5. Последовательность входных проверок

Проверки выполняет `DialogIntakeService.accept()` строго до запуска LLM.

### 5.1. Проверка длительности

Если передан `duration_seconds`, используется он. Иначе длительность вычисляется
по максимальному `utterance.end_ms`.

```text
duration < MIN_DIALOG_DURATION_SECONDS
→ duration_filtered
→ ничего не записывается в PostgreSQL
→ LLM не вызывается
```

По умолчанию минимальная длительность равна 50 секундам.

### 5.2. Определение рабочей даты

При `CALENDAR_FILTER_ENABLED=true` рабочая дата определяется по фактическому
времени получения callback в UTC, а не по региону звонящего.

Правила:

| Время получения | Результат |
|---|---|
| Понедельник–четверг до 18:00 UTC | Текущий день |
| Понедельник–четверг после 18:00 UTC | Следующий календарный рабочий день |
| Пятница до 18:00 UTC | Пятница |
| Пятница после 18:00 UTC | Диалог полностью отбрасывается |
| Суббота | Диалог полностью отбрасывается |
| Воскресенье до 18:00 UTC | Диалог полностью отбрасывается |
| Воскресенье после 18:00 UTC | Понедельник |

Отброшенный диалог получает внутренний outcome `calendar_filtered`, но не
попадает ни в одну таблицу Analyzer.

При `CALENDAR_FILTER_ENABLED=false` календарная фильтрация отключена. Рабочая
дата берётся из `occurred_at`, а при его отсутствии — из текущего времени.
Этот режим предназначен прежде всего для локального E2E.

### 5.3. Проверка менеджера

`ANALYZED_MANAGER_IDS` является белым списком входного анализа.

```text
manager_id отсутствует в ANALYZED_MANAGER_IDS
→ manager_filtered
→ диалог не сохраняется
→ задача не создаётся
→ LLM не вызывается
```

Затем `Settings.analyzers_for(manager_id)` строит обязательную последовательность:

```text
prompt → audio (если включён) → factor (если включён)
```

Prompt Analyzer обязателен для каждого анализируемого менеджера.

### 5.4. Проверка дубликата

Перед INSERT выполняется проверка существующего завершённого отчёта:

```sql
SELECT call_id
FROM analyzer.dialog_reports
WHERE call_id = :call_id;
```

После этого `dialogs` вставляется через `ON CONFLICT DO NOTHING`. Поэтому
повторный callback с тем же `call_id` не запускает второй анализ.

## 6. Первое сохранение в PostgreSQL

Успешно принятый диалог создаёт две записи.

### 6.1. `analyzer.dialogs`

Таблица содержит исходные данные, необходимые для анализа:

- `call_id`, `manager_id`, `client_epk`;
- `work_date`, `occurred_at`, `received_at`;
- `duration_seconds`, `cleaned_text`;
- список `required_analyzers`;
- статус `waiting`;
- версии критериев, промпта и модели;
- `expires_at`.

### 6.2. `analyzer.analysis_tasks`

Создаётся персистентное задание:

- UUID задания;
- `call_id`;
- статус `waiting`;
- `attempt_count=0`;
- `claimed_at=NULL`;
- TTL.

Связь с `dialogs` имеет `ON DELETE CASCADE`. После успешного анализа удаление
`dialogs` автоматически удаляет завершённое задание.

Основные логи:

```text
Dialog callback received call_id=...
Dialog saved call_id=...
Dialog task created call_id=...
```

## 7. Работа Analysis Worker

Worker запускается один раз вместе с FastAPI.

### 7.1. Восстановление после рестарта

После рестарта задания в `processing` возвращаются в `waiting`, у них очищается
`claimed_at`. Связанные `dialogs.status` также возвращаются в `waiting`.

Это означает at-least-once обработку: незавершённая работа будет взята снова.

### 7.2. Опрос очереди

Worker опрашивает PostgreSQL каждые `WORKER_POLL_INTERVAL_SECONDS`.

Размер одного claim:

```text
min(WORKER_CLAIM_LIMIT, DIALOG_PIPELINE_CONCURRENCY)
```

Запрос по смыслу:

```sql
SELECT analysis_tasks.*
FROM analyzer.analysis_tasks
JOIN analyzer.dialogs USING (call_id)
WHERE analysis_tasks.status = 'waiting'
  AND dialogs.work_date <= :latest_allowed_date
ORDER BY dialogs.work_date, analysis_tasks.created_at
LIMIT :claim_limit
FOR UPDATE SKIP LOCKED;
```

`SKIP LOCKED` позволяет нескольким экземплярам worker-а не брать одно задание.

При claim:

- task становится `processing`;
- `claimed_at` получает текущее UTC-время;
- dialog становится `processing`;
- очищаются старые `error_code`.

### 7.3. Ограничение после 18:00 UTC

До cutoff worker может брать диалоги с `work_date <= today`.

После `DASHBOARD_CRON_HOUR_UTC` worker использует последнюю допустимую дату
`today - 1 day`. Поэтому новый `waiting` текущего дня уже не сможет перейти в
`processing` после cutoff.

### 7.4. Параллельность

`DIALOG_PIPELINE_CONCURRENCY` ограничивает число одновременно выполняемых
полных pipeline диалога. Для каждого взятого задания создаётся coroutine, но
одновременно внутрь анализа проходят только задачи, получившие семафор.

Дополнительно все реальные LLM HTTP-запросы используют единый семафор
`GIGACHAT_MAX_CONCURRENCY`. Поэтому:

- pipeline-ов диалогов может быть, например, 10;
- одновременно обращаться к GigaChat может, например, только один запрос.

## 8. Orchestrator одного диалога

Orchestrator читает `dialogs` по `call_id` и последовательно выполняет список
`required_analyzers`.

```text
prompt
  ├─ hygiene LLM
  ├─ deposit LLM
  └─ risk LLM
audio  (если назначен менеджеру)
factor (если назначен менеджеру)
```

Prompt, audio и factor считаются обязательными, если они записаны в
`required_analyzers`. Ошибка любого обязательного шага делает весь диалог
`failed`. Частичный готовый отчёт наружу не выдаётся.

## 9. Три LLM-запроса Prompt Analyzer

### 9.1. Общие правила коммуникации

Первый запрос получает:

- общий system prompt;
- очищенный диалог;
- все активные общие критерии;
- JSON Schema `DialogAnalysisResponse`.

Для каждого критерия модель обязана вернуть:

```json
{"code": "...", "score": 0, "quote": "..."}
```

`score=1` означает выполнение критерия. Для превентивных критериев отсутствие
нарушения тоже означает `1`. `score=0` означает нарушение.

### 9.2. Вклады

Второй запрос анализирует критерии вкладов и всегда содержит gate-критерий
`DEPOSIT_TOPIC`.

Если `DEPOSIT_ANALYSIS_ENABLED=false`, LLM-запрос вкладов пропускается и
система искусственно создаёт `DEPOSIT_TOPIC=0`.

Если после анализа `DEPOSIT_TOPIC=0`:

- остальные вкладовые scores принудительно сохраняются как `0`;
- для них ставится `included_in_analytics=false`;
- они не влияют на оценку диалога;
- они не входят в strengths/improvements;
- они не появляются как нарушения на UI.

Если `DEPOSIT_TOPIC=1`, вкладовые критерии участвуют в математике и аналитике.

### 9.3. Риски

Третий запрос всегда независим от первых двух. Risk Analyzer ничего не знает о
результатах гигиены и вкладов.

Для risk-критерия:

- `score=0` — риск обнаружен;
- `score=1` — риск не обнаружен.

Severity риска задаётся только YAML-каталогом и может быть:

- `high`;
- `medium`;
- `low`.

Риски не влияют на score диалога, Q-score, strengths или improvements.

## 10. Проверка ответа LLM

Ответ проходит несколько уровней проверки:

1. JSON обязан соответствовать Pydantic JSON Schema.
2. Коды не должны повторяться.
3. Набор кодов обязан точно совпадать с каталогом выбранного блока.
4. Если при `score=0` модель вернула цитату, цитата должна буквально
   присутствовать в `cleaned_text`.

Некорректный ответ считается ошибкой LLM-запроса и участвует в retry.

## 11. LLM retries и параметры генерации

GigaChat используют до `GIGACHAT_MAX_ATTEMPTS` попыток. Между
попытками применяется exponential backoff:

```text
GIGACHAT_RETRY_BASE_SECONDS × 2^(attempt-1), максимум 20 секунд
```

Повторяются HTTP-ошибки, невалидный JSON, ошибка Pydantic и отсутствие
обязательных полей.

Для GigaChat передаются:

- `model`;
- `max_tokens`;
- `repetition_penalty`;
- `temperature` или `top_p`;
- strict JSON Schema;
- `stream=false`.

Access token кешируется до истечения срока. Обновление токена защищено lock,
чтобы параллельные запросы не создавали несколько токенов одновременно.

## 12. Математика оценки одного диалога

LLM не вычисляет итоговые баллы. Он возвращает только `0/1` и цитаты.

Для каждого блока:

```text
penalty_sum = сумма penalty всех критериев со score=0
block_score = max(0, 100 - penalty_sum)
```

Если нарушен хотя бы один критерий с `critical=true`:

```text
block_score = min(block_score, 80)
```

Фактический верхний предел итогового диалога задаётся
`CRITICAL_SCORE_CAP`.

### 12.1. Нет темы вкладов

```text
deposit_topic = false
deposit_score = null
final_score = general_score
```

### 12.2. Есть тема вкладов

```text
deposit_topic = true
final_score = (general_score + deposit_score) / 2
```

При критическом нарушении в любом участвующем блоке:

```text
final_score = min(final_score, CRITICAL_SCORE_CAP)
```

`deviations_count` — число участвующих критериев со `score=0`. Неактуальные
вкладовые критерии в это число не входят. `risks_count` считается отдельно и
не влияет на deviations.

## 13. Готовый popup одного диалога

До сохранения формируется `report_payload`, чтобы GET не делал расчётов.

В нём находятся:

- `callId`, `clientEpk`, дата и тип `call`;
- итоговый score;
- количество отклонений;
- список всех выявленных рисков только с `code` и `title`;
- top выполненных критериев;
- top нарушений с названием, severity, рекомендацией и цитатой.

Количество лучших и худших критериев задают `STRENGTHS_LIMIT` и
`IMPROVEMENTS_LIMIT`.

Положительный текст выбирается детерминированно: SHA-256 от `call_id` выбирает
один шаблон из `positive_templates.yaml`. Повторный анализ того же `call_id`
получает тот же вариант текста.

## 14. Атомарное успешное завершение

В одной транзакции:

1. строка `dialogs` блокируется;
2. создаётся или обновляется `dialog_reports`;
3. сохраняются пять независимых JSONB-блоков:
   `hygiene_results`, `deposit_results`, `risk_results`, `audio_results`,
   `factor_results`;
4. сохраняются scores, flags, counts и готовый `report_payload`;
5. удаляется `dialogs`;
6. связанный task удаляется каскадно.

`dialog_reports` является главным источником истины для dashboard и UI.

## 15. Ошибка анализа

Если обязательный шаг окончательно упал:

- `analysis_tasks.status = failed`;
- сохраняются `error_code` и число попыток;
- `dialogs.status = failed`;
- `dialog_reports` не создаётся;
- диалог не попадает ни в один GET и ни в dashboard.

Ручной повтор:

```http
POST /analysis/run/dialog
{"call_id":"..."}
```

Он переводит существующие `failed` dialog/task обратно в `waiting`.

---

# Часть II. E2E-построение dashboard

## 16. Запуск

Автоматический запуск происходит по cron в
`DASHBOARD_CRON_HOUR_UTC`, по умолчанию в `18:00 UTC`.

Ручной запуск использует тот же scheduler и тот же builder:

```http
POST /analysis/run/dashboard?date=YYYY-MM-DD
```

Суббота и воскресенье пропускаются. Dashboard создаётся для каждого менеджера
из четырёх ролевых ENV-списков.

## 17. Cutoff очереди перед расчётом

На старте dashboard для целевой даты выполняются два действия.

### 17.1. Перенос waiting

Все task со статусом `waiting`, связанные с `dialogs.work_date = target_date`,
пакетно блокируются и получают следующий рабочий `work_date`.

Примеры:

- waiting понедельника → вторник;
- waiting четверга → пятница;
- waiting пятницы → понедельник.

Размер пакета задаёт `DASHBOARD_CLEANUP_BATCH_SIZE`. Операция повторяется до
исчерпания waiting.

Scheduler не ждёт эти диалоги. Они будут проанализированы как данные следующего
рабочего дня.

### 17.2. Ожидание processing

Scheduler считает только задачи:

```text
status = processing
claimed_at < cutoff
dialogs.work_date = target_date
```

Если такие задачи есть, проверка повторяется каждые
`DASHBOARD_WAIT_INTERVAL_SECONDS`. Ограничения общего времени ожидания нет.

`waiting` не блокирует dashboard. `failed` не блокирует dashboard. Задание,
которое worker не успел начать до cutoff, относится к следующему рабочему дню.

## 18. Пакетная обработка менеджеров

Менеджеры берутся из:

```text
EFS_VIP_KM_MANAGER_IDS
EFS_AKM_VIP_MANAGER_IDS
EFS_VIP_DSB_MANAGER_IDS
EFS_VIP_TFS_MANAGER_IDS
```

Список делится на пакеты по `DASHBOARD_MANAGER_BATCH_SIZE`.

Для каждого batch выполняются общие SQL-запросы с:

```sql
WHERE manager_id IN (:manager_ids)
```

Вместо отдельного запроса на каждого сотрудника. Это исключает N+1 и не даёт
Python загрузить историю всех менеджеров одновременно.

## 19. Дневной aggregate

Для текущей даты одним запросом читаются completed reports всех менеджеров
пакета:

```sql
SELECT *
FROM analyzer.dialog_reports
WHERE manager_id IN (:manager_ids)
  AND work_date = :report_date
ORDER BY occurred_at;
```

Для каждого менеджера формируется одна строка
`dashboard_aggregates(manager_id, aggregate_date)`.

### 19.1. Дневная статистика диалогов

Сохраняются:

```text
dialogs_count
dialog_score_sum
dialog_score_count
```

`dialog_score_sum` — сумма итоговых scores диалогов дня.

### 19.2. Дневная статистика каждой метрики

Для каждого `metric_code` в `daily_metrics` сохраняются:

- название;
- severity;
- recommendation;
- число `passed`;
- число `failed`;
- общее число `total`;
- список нарушений с `callId`, EPK, временем и цитатой.

Вкладовая метрика учитывается только при
`included_in_analytics=true`, то есть только при актуальной теме вкладов.

### 19.3. Дневные риски

Каждый обнаруженный risk сохраняется в `daily_risks` как событие:

- EPK клиента;
- call ID;
- код и название риска;
- severity `high/medium/low`;
- цитата;
- рекомендация;
- время коммуникации.

## 20. Rolling 30 days для метрик

Окно задаётся `METRIC_ROLLING_WINDOW_DAYS`, по умолчанию 30 календарных дней,
включая `report_date`.

Для каждой метрики:

```text
passed_30 = сумма дневных passed в окне
failed_30 = сумма дневных failed в окне
total_30 = passed_30 + failed_30
percent_30 = passed_30 / total_30 × 100
```

Если вкладовая тема неактуальна, этот диалог отсутствует в `total_30` данной
вкладовой метрики.

Результат сохраняется в `rolling_30_metrics`. Поэтому GET не сканирует сырые
диалоги и не пересчитывает окно.

## 21. Личный квартальный Q-score

Начало квартала вычисляется календарно:

- январь–март;
- апрель–июнь;
- июль–сентябрь;
- октябрь–декабрь.

Q-score менеджера:

```text
quarter_score_sum = сумма final score всех completed диалогов квартала
quarter_dialog_count = количество этих диалогов
personal_q_score = quarter_score_sum / quarter_dialog_count
```

При отсутствии диалогов значение равно `EMPTY_SCORE_VALUE`, по умолчанию 0.

Квартальная сумма и количество сохраняются в `quarter_score_data`, поэтому для
расчёта не требуется повторный LLM-анализ.

## 22. Командный Q-score

Менеджеры группируются по одной из четырёх ролей. Для каждой роли собираются
личные квартальные Q-score всех менеджеров роли и вычисляется медиана.

Пример:

```text
EFS_VIP_KM: [70, 80, 95] → teamMedian = 80
EFS_AKM_VIP: [88]         → teamMedian = 88
```

Менеджер получает teamMedian только своей роли.

## 23. Пять месячных точек Q-score

Для каждого рабочего дня в `month_score_data` сохраняется накопительный Q-score
текущего календарного месяца.

В готовом ответе возвращаются пять месяцев, включая текущий:

- октябрь → июнь, июль, август, сентябрь, октябрь;
- ноябрь → июль, август, сентябрь, октябрь, ноябрь.

Для завершённого месяца берётся последнее сохранённое значение месяца. Для
текущего — значение по `report_date`. Если данных нет, возвращается
`EMPTY_SCORE_VALUE` и `communicationsCount=0`.

## 24. Завершённая недельная точка

Недельная точка формируется только в пятницу после cutoff.

Период подписи:

```text
понедельник — воскресенье
```

Фактические звонки:

```text
понедельник — пятница
```

Для каждой метрики сохраняются недельные `passed`, `failed`, `total`, `percent`
и нарушения. Это единый JSONB `weekly_metrics`, а не отдельные строки по каждой
метрике.

## 25. Блок «Получается отлично»

Источник — `rolling_30_metrics`.

Условие попадания:

```text
currentPercent >= STRENGTH_MIN_PERCENT
```

По умолчанию граница равна 80%.

Ранжирование:

1. большее число успешных коммуникаций `passedCount`;
2. больший процент выполнения;
3. код метрики для стабильного порядка.

Возвращается top `STRENGTHS_LIMIT`, по умолчанию top-3.

Для каждой карточки сохраняются:

- metric code и title;
- severity;
- current percent;
- previous percent;
- delta;
- passed/failed/total;
- recommendation.

## 26. Блок «Нужно улучшить»

Источник тот же — rolling 30 days.

Условие:

```text
currentPercent < STRENGTH_MIN_PERCENT
```

Ранжирование:

1. уровень критичности метрики;
2. большее число нарушений `failedCount`;
3. меньший процент выполнения;
4. код метрики.

Порядок severity в текущем коде:

```text
fraud → high → critical → medium → significant → low → minor → info
```

Возвращается top `IMPROVEMENTS_LIMIT`, по умолчанию top-3.

## 27. Previous percent и delta

`previousPercent` берётся из последнего aggregate строго раньше `report_date`.
Так как aggregates строятся по рабочим дням, в понедельник предыдущим обычно
является пятница.

Формула зафиксирована бизнес-правилом:

```text
delta = previousPercent - currentPercent
```

Пример:

```text
previous = 90
current = 80
delta = +10
```

Положительная delta в данной формуле означает снижение current относительно
previous. Интерпретацию цвета выполняет frontend.

## 28. Popup конкретной метрики «Нужно улучшить»

Для каждой метрики из top improvements заранее сохраняются:

- карточка текущего 30-дневного состояния;
- recommendation;
- последние завершённые недельные точки;
- последние коммуникации, где метрика получила `score=0`.

Число недель задаёт `METRIC_WEEKLY_POINTS_LIMIT`, по умолчанию четыре.

Число коммуникаций с нарушением задаёт
`METRIC_FAILED_COMMUNICATIONS_LIMIT`, по умолчанию три.

Текущая незавершённая неделя в график не попадает. После пятничного cutoff она
становится первой, самой свежей завершённой точкой.

## 29. Блок клиентских рисков

Окно задаётся `RISK_ROLLING_WINDOW_DAYS`, по умолчанию 10 календарных дней,
включая `report_date`.

Сначала события группируются по `client_epk`, затем внутри клиента — по
`metricCode` риска.

У одного клиента допускаются:

- несколько разных рисков в одном звонке;
- одинаковый риск в нескольких звонках;
- несколько разных рисков в нескольких звонках.

Для каждого конкретного риска выбирается самое свежее событие. Из него берутся
последняя цитата, call ID, время и рекомендация. Количество коммуникаций
считается по числу уникальных call ID для этого риска.

### 29.1. Общий уровень клиента

Общий уровень определяется максимальной severity среди всех рисков клиента:

```text
есть хотя бы один high   → high
иначе есть хотя бы medium → medium
иначе                     → low
```

Других уровней нет.

Карточки группируются в порядке `high → medium → low`. Внутри одного уровня
дополнительного бизнес-ранжирования нет. Backend не ограничивает число
клиентов — возвращаются все клиенты окна.

### 29.2. Основной risk-блок

Для клиента сохраняются:

- EPK;
- общий уровень;
- количество разных рисков;
- количество уникальных коммуникаций;
- дата последнего события;
- список названий рисков для тегов.

### 29.3. Popup клиента

Для каждого риска клиента возвращаются:

- EPK;
- код и название;
- severity;
- последняя цитата;
- последний call ID и дата;
- число уникальных коммуникаций с этим риском;
- рекомендация.

## 30. Блок коммуникаций

Для snapshot пакетно выбираются последние completed reports каждого менеджера.
В PostgreSQL используется `row_number() over (partition by manager_id order by
occurred_at desc)`, поэтому нет отдельного запроса на менеджера.

В snapshot сохраняются последние `LATEST_COMMUNICATIONS_LIMIT` звонков.

Карточка содержит:

- call ID;
- тип `call`;
- EPK;
- дату и время;
- итоговый score диалога.

## 31. Отсутствие звонков у менеджера

Для каждого менеджера из четырёх ролевых списков создаётся snapshot каждого
рабочего дня, даже если в этот день нет completed reports.

Если предыдущий snapshot существует:

- персональные risk/strength/improvement/communication блоки копируются;
- `source_date` сохраняет дату исходных данных;
- `carried_forward=true`;
- Q-score пересчитывается по календарю, чтобы корректно обработать новый
  квартал, новый месяц и командную медиану.

Если предыдущей витрины нет, создаётся нулевая витрина.

## 32. Сохранение aggregate

`dashboard_aggregates` имеет уникальность:

```text
(manager_id, aggregate_date)
```

Сохраняются отдельные поля:

- роль;
- дневные count/sum;
- `daily_metrics`;
- `daily_risks`;
- `rolling_30_metrics`;
- `weekly_metrics`;
- `quarter_score_data`;
- `month_score_data`.

Сохранение выполняется bulk-upsert для всего batch. Повторный ручной запуск той
же даты обновляет строку, а не создаёт дубликат.

## 33. Сохранение готового snapshot

`dashboard_snapshots` имеет уникальность:

```text
(manager_id, report_date)
```

В одной строке уже лежат готовые данные UI:

- Q-score;
- все клиенты риска;
- risk popup по EPK;
- strengths;
- improvements;
- improvement popup по metric code;
- список коммуникаций;
- source call IDs;
- `source_date`, `carried_forward`, роль.

GET не выполняет тяжёлую математику. Повторная сборка даты делает bulk-upsert.

## 34. Сжатие истории и TTL

TTL всех пяти таблиц задаёт `DATA_TTL_DAYS`, по умолчанию 183 дня.

После построения dashboard тяжёлые части старой истории очищаются:

- `daily_risks` после окончания risk-window;
- `daily_metrics` и `rolling_30_metrics` после окончания metric-window;
- старые `weekly_metrics`, которые уже не нужны для последних недель.

При этом компактные дневные score sum/count, квартальные и месячные данные
остаются до TTL. Поэтому будущий Q-score не требует чтения полного JSON каждого
старого диалога.

Физическое удаление просроченных строк идёт пакетами по
`DASHBOARD_CLEANUP_BATCH_SIZE`, чтобы одна транзакция не удаляла сразу большой
объём.

---

# Часть III. Восемь GET-ручек

## 35. Общие правила GET

`manager_id` нормализуется до восьми цифр. `date` обязателен для dashboard GET.
Backend ищет строго запрошенную дату и не подменяет её последним доступным
snapshot.

Если snapshot или report отсутствует, API возвращает `404`.

## 36. GET 1 — Q-score

```http
GET /manager/{manager_id}/q-score?date=YYYY-MM-DD
```

SQL по смыслу:

```sql
SELECT q_score_block
FROM analyzer.dashboard_snapshots
WHERE manager_id = :manager_id
  AND report_date = :date;
```

Ответ содержит:

- личный квартальный Q-score;
- командную медиану по роли;
- число коммуникаций квартала;
- пять месячных точек.

## 37. GET 2 — все клиенты в зоне риска

```http
GET /manager/{manager_id}/client-risks?date=YYYY-MM-DD
```

Читается готовый `client_risks_block` из одной строки snapshot. Возвращаются
все клиенты 10-дневного окна с risk tags и общим уровнем high/medium/low.

## 38. GET 3 — popup конкретного клиента

```http
GET /manager/{manager_id}/client-risks/{client_epk}?date=YYYY-MM-DD
```

Сначала читается одна строка snapshot, затем в памяти выполняется lookup:

```text
client_risk_details[client_epk]
```

Новых SQL-запросов по отдельным рискам и диалогам нет.

## 39. GET 4 — strengths

```http
GET /manager/{manager_id}/strengths?date=YYYY-MM-DD
```

Читается `strengths_block`. Это готовый top метрик с процентами и delta.

## 40. GET 5 — improvements

```http
GET /manager/{manager_id}/improvements?date=YYYY-MM-DD
```

Читается `improvements_block`. Это готовый top метрик ниже порога.

## 41. GET 6 — popup конкретной improvement-метрики

```http
GET /manager/{manager_id}/improvements/{metric_code}?date=YYYY-MM-DD
```

После чтения snapshot выполняется lookup:

```text
improvement_details[metric_code]
```

Ответ содержит текущую карточку, четыре завершённые недели и звонки с
нарушением.

## 42. GET 7 — список коммуникаций

```http
GET /manager/{manager_id}/dialogs?date=YYYY-MM-DD
```

Этот GET читает не snapshot, а `dialog_reports`, потому что поддерживает
динамические фильтры:

- `client_epk`;
- `date_from`;
- `date_to`;
- `type=call`;
- `limit`.

Базовый фильтр:

```sql
WHERE manager_id = :manager_id
  AND work_date <= :date
ORDER BY occurred_at DESC
LIMIT :limit
```

Если `limit` не указан, используется `LATEST_COMMUNICATIONS_LIMIT`. Значение не
может превышать `COMMUNICATIONS_MAX_LIMIT`.

Наружу попадают только completed reports, потому что запрос идёт в
`dialog_reports`. `waiting`, `processing`, `failed` там отсутствуют.

## 43. GET 8 — popup одного диалога

```http
GET /manager/dialogs/{call_id}
```

SQL:

```sql
SELECT report_payload
FROM analyzer.dialog_reports
WHERE call_id = :call_id;
```

Возвращается заранее сформированный payload без нового LLM-вызова и без
пересчёта score.

## 43.1. Ориентировочные формы ответов

Q-score:

```json
{
  "personal": 86.4,
  "teamMedian": 82.1,
  "communicationsCount": 41,
  "months": [
    {"year": 2026, "month": 7, "qScore": 80.0, "communicationsCount": 20}
  ]
}
```

Основной risk-блок:

```json
{
  "items": [
    {
      "clientEpk": "EPK-001",
      "level": "high",
      "risksCount": 2,
      "communicationsCount": 3,
      "latestOccurredAt": "2026-11-02T12:00:00+00:00",
      "riskTags": ["Клиент собирается уйти", "Не устраивают условия"]
    }
  ]
}
```

Popup клиента:

```json
{
  "clientEpk": "EPK-001",
  "level": "high",
  "risks": [
    {
      "clientEpk": "EPK-001",
      "metricCode": "CLIENT_WANTS_TO_LEAVE",
      "title": "Клиент собирается уйти в другой банк",
      "severity": "high",
      "latestQuote": "Я уйду в другой банк",
      "latestCallId": "call-100",
      "latestOccurredAt": "2026-11-02T12:00:00+00:00",
      "communicationsCount": 2,
      "recommendation": "Уточните причину недовольства"
    }
  ]
}
```

Strengths и improvements используют одинаковую основу карточки:

```json
{
  "metricCode": "GREETING",
  "title": "Приветствие",
  "severity": "minor",
  "currentPercent": 90.0,
  "previousPercent": 85.0,
  "delta": -5.0,
  "passedCount": 9,
  "failedCount": 1,
  "communicationsCount": 10,
  "recommendation": "Используйте корректное приветствие"
}
```

Popup improvement дополнительно содержит:

```json
{
  "weekly": [
    {"from": "2026-10-05", "to": "2026-10-11", "percent": 75.0}
  ],
  "communications": [
    {
      "callId": "call-101",
      "type": "call",
      "clientEpk": "EPK-002",
      "occurredAt": "2026-11-01T10:00:00+00:00",
      "quote": "Цитата нарушения"
    }
  ]
}
```

Строка списка коммуникаций:

```json
{
  "callId": "call-101",
  "type": "call",
  "clientEpk": "EPK-002",
  "occurredAt": "2026-11-01T10:00:00+00:00",
  "score": 84.0
}
```

Popup одного диалога:

```json
{
  "callId": "call-101",
  "clientEpk": "EPK-002",
  "occurredAt": "2026-11-01T10:00:00+00:00",
  "type": "call",
  "score": 84.0,
  "deviationsCount": 2,
  "risks": [
    {"code": "CLIENT_DISLIKES_BANK_TERMS", "title": "Клиента не устраивают условия банка"}
  ],
  "strengths": {
    "text": "Вы хорошо выполнили следующие критерии...",
    "metrics": [{"code": "GREETING", "title": "Приветствие"}]
  },
  "improvements": [
    {
      "code": "NEXT_STEP",
      "title": "Согласование следующего шага",
      "severity": "significant",
      "recommendation": "Согласуйте следующий шаг",
      "quote": "Я вам потом перезвоню"
    }
  ]
}
```

---

# Часть IV. Таблицы и индексы

## 44. Пять таблиц

| Таблица | Жизненный цикл |
|---|---|
| `dialogs` | От принятия callback до успешного анализа либо TTL ошибки |
| `analysis_tasks` | Персистентная очередь waiting/processing/failed |
| `dialog_reports` | Готовый анализ звонка и источник dashboard |
| `dashboard_aggregates` | Промежуточная математика manager/date |
| `dashboard_snapshots` | Готовые ответы UI manager/date |

Отдельных таблиц utterances, metric history, weekly reports, monthly reports и
quarterly reports нет.

## 45. Основные индексы

- `dialogs(status, work_date, created_at)` — claim очереди;
- `dialogs(manager_id, work_date)` — рабочая дата менеджера;
- `analysis_tasks(status, created_at)` — waiting queue;
- `analysis_tasks(status, claimed_at)` — ожидание cutoff processing;
- `dialog_reports(work_date, manager_id)` — дневной batch dashboard;
- `dialog_reports(manager_id, work_date, occurred_at)` — история менеджера;
- `dialog_reports(manager_id, client_epk, occurred_at)` — фильтр клиента;
- unique `dashboard_aggregates(manager_id, aggregate_date)`;
- unique `dashboard_snapshots(manager_id, report_date)`.

## 45.1. Карта логов и наблюдаемости

Успешный путь одного диалога можно искать по `call_id`:

```text
Dialog callback received
Dialog saved
Dialog task created
Tasks claimed
Task started
Dialog analysis started
Agent started name=prompt
Hygiene analysis started/completed
Deposit analysis started/completed
Risk analysis started/completed
LLM response body=...
Agent response received
Dialog result saved
Task completed
```

Фильтры до БД дают короткие события:

```text
Dialog too short
Dialog skipped by calendar
Dialog manager skipped
Dialog duplicate ignored
```

Ошибка worker-а:

```text
Task failed call_id=... error=...
```

Dashboard:

```text
Waiting moved date=... count=...
Dashboard waits tasks count=...
Dashboard build started date=... managers=...
Dashboard build completed date=...
```

GET:

```text
Dashboard GET manager_id=... date=...
Dialog GET received call_id=...
Dialog GET returned call_id=... score=...
```

На `/metrics` публикуются Prometheus-метрики callback, результатов jobs,
активных GigaChat-запросов и outcome обращений к модели. Логи полного ответа
LLM управляются `LOG_LLM_RESPONSES`.

---

# Часть V. Все ENV/ConfigMap Analyzer

## 46. Общие и логирование

| ENV | Default | Использование |
|---|---:|---|
| `SERVICE_NAME` | `analyzer` | Имя сервиса. Сейчас хранится в Settings, но отдельно в бизнес-логике не используется |
| `LOG_LEVEL` | `INFO` | Уровень Python-логирования |
| `LOG_LLM_RESPONSES` | `true` | Разрешает полный лог структурированного ответа LLM |

Полный LLM-ответ может содержать цитаты клиента. В production значение
`LOG_LLM_RESPONSES` следует согласовать с требованиями к персональным данным.

## 47. PostgreSQL

| ENV | Default | Использование |
|---|---:|---|
| `DB_USER` | `quality` | Пользователь PostgreSQL |
| `DB_PASS` / `DB_PASSWORD` | `quality` | Пароль; должен приходить из Secret |
| `DB_NAME` | `quality` | Имя базы |
| `POSTGRES_HOSTS` | `postgres:5432` | Один или несколько `host:port` через запятую |
| `POSTGRES_DSN` | пусто | Полная замена автоматически построенного DSN |
| `POSTGRES_SCHEMA` | `analyzer` | Зарезервировано в Settings; модели сейчас используют фиксированную схему `analyzer` |
| `POSTGRES_POOL_SIZE` | `10` | Постоянный размер connection pool |
| `POSTGRES_MAX_OVERFLOW` | `20` | Дополнительные соединения при пике |
| `POSTGRES_POOL_RECYCLE_SECONDS` | `3600` | Переоткрытие старых соединений |

Для нескольких hosts формируется asyncpg DSN с
`target_session_attrs=read-write`, то есть выбирается writable primary.

## 48. Менеджеры и анализаторы

| ENV | Использование |
|---|---|
| `ANALYZED_MANAGER_IDS` | Белый список приёма диалогов |
| `PROMPT_ANALYZER_MANAGER_IDS` | Назначение обязательной prompt-цепочки |
| `AUDIO_ANALYZER_MANAGER_IDS` | Назначение внешнего audio-анализа |
| `FACTOR_ANALYZER_MANAGER_IDS` | Назначение внешнего factor-анализа |
| `EFS_VIP_KM_MANAGER_IDS` | Состав роли для dashboard/team median |
| `EFS_AKM_VIP_MANAGER_IDS` | Состав роли для dashboard/team median |
| `EFS_VIP_DSB_MANAGER_IDS` | Состав роли для dashboard/team median |
| `EFS_VIP_TFS_MANAGER_IDS` | Состав роли для dashboard/team median |
| `AUDIO_ANALYZER_URL` | URL внешнего audio-сервиса |
| `FACTOR_ANALYZER_URL` | URL внешнего factor-сервиса |
| `EXTERNAL_ANALYZER_TIMEOUT_SECONDS` | HTTP timeout audio/factor, default 300 секунд |

## 49. Worker и фильтры

| ENV | Default | Использование |
|---|---:|---|
| `WORKER_POLL_INTERVAL_SECONDS` | `30` | Интервал polling очереди |
| `WORKER_CLAIM_LIMIT` | `100` | Верхняя граница claim |
| `DIALOG_PIPELINE_CONCURRENCY` | `10` | Семафор полных pipeline диалога |
| `MIN_DIALOG_DURATION_SECONDS` | `50` | Фильтр коротких звонков до БД |
| `DATA_TTL_DAYS` | `183` | TTL всех данных Analyzer |
| `CALENDAR_FILTER_ENABLED` | `true` | Рабочий календарь и правила после 18:00 UTC |
| `DEPOSIT_ANALYSIS_ENABLED` | `true` | Включение второго LLM-запроса по вкладам |

## 50. Выбор LLM

| ENV | Default | Использование |
|---|---:|---|
| `LLM_PROVIDER` | `gigachat` | `gigachat` для production либо для локального E2E |
| `ACTIVE_CRITERIA_CODES` | пусто | Ограничивает общие критерии; deposit и risk остаются обязательными |
| `CRITERIA_VERSION` | `prompt-4q-v1` | Сохраняется в dialog/report для трассировки |
| `PROMPT_VERSION` | `prompt-4q-v1` | Сохраняется в dialog/report для трассировки |
| `REPORT_VERSION` | `v1` | Сейчас зарезервировано и не влияет на payload или запросы |

## 51. GigaChat

| ENV | Default | Использование |
|---|---:|---|
| `GIGACHAT_AUTH_URL` | OAuth URL | Получение access token |
| `GIGACHAT_BASE_URL` | API URL | `/chat/completions` и `/tokens/count` |
| `GIGACHAT_CREDENTIALS` | пусто | Basic credentials, должны приходить из Secret |
| `GIGACHAT_SCOPE` | `GIGACHAT_API_CORP` | OAuth scope |
| `GIGACHAT_MODEL` | `GigaChat-2-Pro` | Модель и значение model_name в report |
| `GIGACHAT_VERIFY_SSL` | `true` | Проверка TLS |
| `GIGACHAT_CERT_FILE` | пусто | Клиентский сертификат при mTLS |
| `GIGACHAT_KEY_FILE` | пусто | Ключ сертификата; задаётся вместе с CERT_FILE |
| `GIGACHAT_TIMEOUT_SECONDS` | `120` | Таймаут HTTP; также используется provider |
| `GIGACHAT_MAX_CONCURRENCY` | `1` | Общий семафор LLM HTTP-запросов |
| `GIGACHAT_MAX_ATTEMPTS` | `5` | Число попыток одного LLM-запроса |
| `GIGACHAT_RETRY_BASE_SECONDS` | `1` | База exponential backoff |
| `GIGACHAT_TEMPERATURE` | `0.1` | Temperature; нельзя вместе с TOP_P |
| `GIGACHAT_TOP_P` | `null` | Альтернатива temperature |
| `GIGACHAT_MAX_OUTPUT_TOKENS` | `8000` | `max_tokens` ответа |
| `GIGACHAT_REPETITION_PENALTY` | `1.0` | Repetition penalty |
| `GIGACHAT_MAX_INPUT_TOKENS` | `116000` | Контекст; для текущего одиночного GigaChat-запроса жёсткая pre-check граница пока не применяется |
| `GIGACHAT_PROMPT_RESERVE_TOKENS` | `2000` | Резервная настройка старого batch-планирования; сейчас не участвует в двух процессах |
| `GIGACHAT_OUTPUT_RESERVE_TOKENS` | `8000` | Резервная настройка старого batch-планирования; сейчас не участвует |
| `AGGREGATION_MAX_BATCH_ITEMS` | `15` | Остаток старой логики агрегированных LLM-отчётов; текущий dashboard его не использует |

Последние три настройки оставлены для совместимости конфигурации. Аналитику не
следует считать их действующими ограничениями dashboard.

## 53. Dashboard

| ENV | Default | Использование |
|---|---:|---|
| `DASHBOARD_ENABLED` | `true` | Включает автоматический cron |
| `DASHBOARD_CRON_HOUR_UTC` | `18` | Cutoff и час сборки |
| `DASHBOARD_WAIT_INTERVAL_SECONDS` | `30` | Частота проверки processing |
| `DASHBOARD_MANAGER_BATCH_SIZE` | `100` | Размер пакета менеджеров для SQL и памяти |
| `DASHBOARD_CLEANUP_BATCH_SIZE` | `1000` | Пакет rollover и TTL delete |
| `METRIC_ROLLING_WINDOW_DAYS` | `30` | Окно strengths/improvements |
| `RISK_ROLLING_WINDOW_DAYS` | `10` | Окно client risks |
| `STRENGTH_MIN_PERCENT` | `80` | Граница strengths/improvements |
| `STRENGTHS_LIMIT` | `3` | Top strengths и popup диалога |
| `IMPROVEMENTS_LIMIT` | `3` | Top improvements и popup диалога |
| `LATEST_COMMUNICATIONS_LIMIT` | `5` | Default списка коммуникаций |
| `COMMUNICATIONS_MAX_LIMIT` | `100` | Максимум API limit |
| `METRIC_FAILED_COMMUNICATIONS_LIMIT` | `3` | Звонки в popup improvement |
| `METRIC_WEEKLY_POINTS_LIMIT` | `4` | Завершённые недели popup improvement |
| `CRITICAL_SCORE_CAP` | `80` | Максимальный score при критическом нарушении |
| `EMPTY_SCORE_VALUE` | `0` | Score при отсутствии данных |

## 54. Тестовая история

| ENV | Default | Использование |
|---|---:|---|
| `TEST_DATA_API_ENABLED` | `false` | Включает `/analysis/run/dashboard-test-data` |
| `TEST_DATA_DEFAULT_DAYS` | `45` | Число дней fixture-истории по умолчанию |

Тестовая ручка создаёт готовые `dialog_reports`, затем вызывает тот же
production `DashboardBuilder`. В production должна быть выключена.

## 54.1. ENV внешнего пути до Analyzer

Следующие переменные находятся в общем `.env.example`, но не читаются
`analyzer/app/config.py`. Они участвуют в upstream-пути Kafka → Consumer → Data
Cleaner → Analyzer либо в локальной инфраструктуре.

| ENV | Сервис | Влияние на E2E |
|---|---|---|
| `POSTGRES_DB` | Docker PostgreSQL | Создаёт базу `quality` |
| `POSTGRES_USER` | Docker PostgreSQL | Создаёт пользователя БД |
| `POSTGRES_PASSWORD` | Docker PostgreSQL | Пароль контейнера; в production Secret |
| `POSTGRES_HOST_PORT` | Docker Compose | Порт PostgreSQL на компьютере пользователя; внутри Docker остаётся 5432 |
| `KAFKA_BOOTSTRAP_SERVERS` | Producer/Consumer | Адрес Kafka-кластера |
| `KAFKA_TOPIC` | Producer/Consumer | Topic исходных коммуникаций |
| `KAFKA_GROUP_ID` | Kafka Consumer | Consumer group и управление offset |
| `KAFKA_MAX_MESSAGE_SIZE` | Kafka-клиенты | Верхний размер сообщения/chunk |
| `CLEANER_BASE_URL` | Kafka Consumer | HTTP-адрес Data Cleaner |
| `CLEANER_TIMEOUT_SECONDS` | Kafka Consumer | Таймаут передачи собранного диалога в Cleaner |
| `CLEANER_CALLBACK_URLS` | Data Cleaner | Список callback; для данного E2E должен содержать URL Analyzer `/internal/v1/dialogs/cleaned` |
| `CLEANER_POLL_INTERVAL_SECONDS` | Data Cleaner | Интервал чтения своей персистентной очереди |
| `CLEANER_WORKER_BATCH_SIZE` | Data Cleaner | Размер batch очистки диалогов |
| `CLEANER_CALLBACK_CONCURRENCY` | Data Cleaner | Число параллельных callback в Analyzer |
| `CLEANER_CALLBACK_QUEUE_SIZE` | Data Cleaner | Ограничение очереди готовых callback в памяти/хранилище Cleaner |
| `CLEANER_CALLBACK_TIMEOUT_SECONDS` | Data Cleaner | Таймаут POST в Analyzer |
| `CHUNK_STORAGE_ENCRYPTED` | Consumer/Cleaner | Признак шифрования промежуточных chunks |
| `CLEANER_REQUEST_ENCRYPTED` | Consumer/Cleaner | Признак шифрования HTTP payload Cleaner |
| `CRYPTO_KEY` | Consumer/Cleaner | AES-ключ; должен храниться в Secret, не в ConfigMap |
| `UCP_BASE_URL` | Data Cleaner | Адрес внешнего UCP для обогащения данных |
| `UCP_TIMEOUT_SECONDS` | Data Cleaner | Таймаут UCP |

Эти настройки определяют, дойдёт ли очищенный диалог до первой точки Analyzer,
но после успешного `POST /internal/v1/dialogs/cleaned` не участвуют в scoring и
dashboard-математике.

---

## 55. Краткая последовательность для тестировщика

### Проверка процесса 1

1. Убедиться, что manager ID находится в `ANALYZED_MANAGER_IDS`,
   `PROMPT_ANALYZER_MANAGER_IDS` и ровно одном role-list.
2. Отправить callback длительностью не менее минимальной.
3. Проверить `dialogs=waiting` и `analysis_tasks=waiting`.
4. Дождаться claim: оба статуса должны стать `processing`.
5. В логах увидеть hygiene, deposit и risk последовательно.
6. После успеха проверить отсутствие строки в `dialogs/tasks`.
7. Проверить одну строку в `dialog_reports` и все три JSONB анализа.
8. Вызвать GET popup и убедиться, что новый LLM-запрос не выполняется.

### Проверка процесса 2

1. Подготовить несколько completed reports разных дат и менеджеров.
2. Запустить dashboard для рабочего дня.
3. Проверить rollover оставшихся waiting.
4. Проверить ожидание только processing до cutoff.
5. Проверить одну aggregate и одну snapshot строку на manager/date.
6. Сверить 30-дневные проценты вручную на небольшой выборке.
7. Сверить `delta = previous - current`.
8. Сверить teamMedian только внутри одной роли.
9. Проверить high/medium/low по максимальному риску клиента.
10. Проверить четыре завершённые недели в popup improvement.
11. Проверить пять месячных точек Q-score.
12. Вызвать все восемь GET и убедиться, что первые шесть читают snapshot,
    список — dialog_reports с фильтрами, popup диалога — готовый report_payload.

