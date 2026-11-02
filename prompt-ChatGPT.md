# Контекст проекта Communication Quality Analyzer для ChatGPT

Используй этот документ как исходный контекст проекта. Не придумывай новую
бизнес-логику поверх описанной. Если требования противоречат друг другу,
сначала укажи конкретное противоречие и задай один точный вопрос.

## 1. Что это за проект

Это backend-система оценки качества телефонных коммуникаций банковских
менеджеров.

Основной микросервис — Analyzer. Он:

1. получает очищенный диалог от Data Cleaner;
2. фильтрует его;
3. выполняет три независимых анализа через GigaChat;
4. детерминированно считает оценку одного диалога;
5. сохраняет готовый отчёт;
6. ежедневно в 18:00 UTC строит готовую dashboard-витрину;
7. отдаёт frontend восемь GET-ручек без тяжёлых вычислений во время GET.

В рабочем проекте используется только GigaChat. Ollama, LLaMA и другие
локальные LLM не являются частью production-решения и не должны предлагаться
как действующая архитектура.

## 2. Архитектурные правила

Код строится по простой clean architecture:

```text
api/          HTTP endpoints, валидация параметров и коды ответа
services/     бизнес-процессы
agents/       промпты, PromptLoader и обращения в GigaChat
database/     модели, connection и repositories
schemas/      Pydantic-модели
```

Правила:

- API не содержит бизнес-математику.
- Services не пишут SQL напрямую.
- Repositories содержат только операции PostgreSQL.
- Agents не знают о dashboard и других agents.
- Промпты и критерии находятся только в Markdown/YAML, не в Python-строках.
- GigaChat возвращает структурированный ответ по strict JSON Schema.
- Комментарии и docstrings пишутся по-русски.
- Логи пишутся коротким английским языком уровня A2–B1.
- Код должен быть понятен junior-разработчику.
- Не создавать абстракции и таблицы без реальной необходимости.
- Настраиваемые числа, переключатели, лимиты и URL выносятся в ENV/ConfigMap.
- Пароли, credentials и ключи должны приходить из Secret, а не ConfigMap.

## 3. Два главных процесса

В Analyzer есть только два тяжёлых процесса:

### Процесс A: анализ одного диалога

```text
Data Cleaner callback
→ фильтры
→ dialogs + analysis_tasks
→ worker
→ hygiene GigaChat
→ deposit GigaChat
→ risk GigaChat
→ Python scoring
→ dialog_reports
→ удаление dialogs и completed task
```

### Процесс B: построение dashboard

```text
cron/manual run в 18:00 UTC
→ перенос waiting
→ ожидание processing до cutoff
→ batch-чтение dialog_reports
→ dashboard_aggregates
→ математика окон и рейтингов
→ dashboard_snapshots
→ восемь GET
```

LLM вызывается только при анализе одного диалога. Dashboard не вызывает
GigaChat.

## 4. Входной диалог

Analyzer принимает:

```http
POST /internal/v1/dialogs/cleaned
```

Главные поля:

- `call_id` — уникальный ID звонка;
- `manager_id` — восьмизначный табельный номер;
- `client_epk` — идентификатор клиента;
- `duration_seconds`;
- `occurred_at`;
- `cleaned_text` с размеченными ролями сотрудника и клиента;
- участники и другие служебные поля.

Отдельная таблица utterances не нужна. В Analyzer хранится цельный cleaned text.

## 5. Фильтры до PostgreSQL

### Длительность

Диалог короче `MIN_DIALOG_DURATION_SECONDS`, по умолчанию 50 секунд:

- не сохраняется;
- не анализируется;
- не попадает в UI и dashboard;
- считается так, будто его не существовало.

### Менеджер

Менеджер должен присутствовать в `ANALYZED_MANAGER_IDS`.

Prompt Analyzer обязателен для каждого анализируемого менеджера. Дополнительно
в будущем могут назначаться Audio и Factor Analyzer.

### Календарь

При включённом календарном фильтре:

| Получение callback | Действие |
|---|---|
| Пн–Чт до 18:00 UTC | Текущий рабочий день |
| Пн–Чт после 18:00 UTC | Следующий рабочий день |
| Пт до 18:00 UTC | Пятница |
| Пт после 18:00 UTC | Полностью пропустить |
| Суббота | Полностью пропустить |
| Воскресенье до 18:00 UTC | Полностью пропустить |
| Воскресенье после 18:00 UTC | Понедельник |

### Дубликат

`call_id` уникален. Повторный callback не создаёт повторный анализ.

## 6. Очередь worker-а

После принятия создаются:

- `dialogs` со статусом `waiting`;
- `analysis_tasks` со статусом `waiting`.

Worker опрашивает очередь с интервалом из ENV и использует
`FOR UPDATE SKIP LOCKED`.

Размер claim:

```text
min(WORKER_CLAIM_LIMIT, DIALOG_PIPELINE_CONCURRENCY)
```

При claim task и dialog становятся `processing`, task получает `claimed_at`.

После рестарта незавершённые `processing` возвращаются в `waiting`.

## 7. Cutoff в 18:00 UTC

При старте dashboard:

1. `waiting` целевой даты не ожидаются;
2. они переносятся на следующий рабочий день;
3. dashboard ждёт только `processing`, которые получили `claimed_at` до cutoff;
4. `failed` dashboard не блокируют;
5. общее время ожидания processing не ограничено;
6. worker после cutoff не может взять новый waiting текущего дня.

Приоритет — своевременно построить dashboard. Не начатые диалоги незаметно для
менеджера учитываются на следующий рабочий день.

## 8. Три независимых GigaChat-запроса

Запросы выполняются последовательно для каждого диалога.

### 8.1. Hygiene

Проверяются общие правила коммуникации. Для каждого критерия GigaChat
возвращает:

```json
{"code":"...","score":0,"quote":"..."}
```

`score=1` — выполнено или нарушение отсутствует. `score=0` — нарушение.

### 8.2. Deposits

Запрос содержит критерий `DEPOSIT_TOPIC`.

Если `DEPOSIT_TOPIC=0`:

- остальные вкладовые scores сохраняются нулями;
- `included_in_analytics=false`;
- вкладовые критерии полностью исключаются из score, Q-score, strengths,
  improvements и UI-недостатков.

Если `DEPOSIT_TOPIC=1`, вкладовые критерии участвуют в математике.

### 8.3. Risks

Риски независимы от hygiene и deposits. Они не влияют на score и Q-score.

Для risk-критерия:

- `score=0` — риск выявлен;
- `score=1` — риск отсутствует.

Risk severity может быть только:

- `high`;
- `medium`;
- `low`.

## 9. Проверка GigaChat-ответа

- JSON валидируется Pydantic-моделью.
- Набор кодов должен точно совпасть с YAML-каталогом блока.
- Повторяющиеся коды запрещены.
- Возвращённая цитата нарушения должна буквально находиться в cleaned text.
- Все критерии блока обязательны.
- Recommendation критерия не может быть пустой.

Ошибочный ответ повторяется до `GIGACHAT_MAX_ATTEMPTS` с exponential backoff.

Все реальные запросы проходят через общий семафор
`GIGACHAT_MAX_CONCURRENCY`.

## 10. Математика одного диалога

GigaChat классифицирует, Python считает.

```text
penalty_sum = сумма penalty критериев со score=0
block_score = max(0, 100 - penalty_sum)
```

При критическом нарушении:

```text
block_score = min(block_score, CRITICAL_SCORE_CAP)
```

Без темы вкладов:

```text
final_score = general_score
deposit_score = null
```

С темой вкладов:

```text
final_score = (general_score + deposit_score) / 2
```

Риски в этой формуле не участвуют.

## 11. Результат одного диалога

Успешный анализ сохраняется в `dialog_reports`:

- cleaned text;
- hygiene results;
- deposit results;
- risk results;
- будущие audio/factor results;
- general/deposit/final score;
- deposit topic;
- critical flag;
- deviations count;
- risks count;
- готовый `report_payload` для GET;
- версии критериев, промпта и модели.

После успешной транзакции входной `dialogs` удаляется. Связанный completed task
удаляется каскадно.

При ошибке dialog/task становятся `failed`, report не создаётся и наружу ничего
не показывается. Ручной endpoint может вернуть failed в `waiting`.

Popup одного диалога возвращает:

- EPK, дату, время и итоговую оценку;
- число отклонений;
- названия всех выявленных рисков;
- top-3 сильных критериев;
- top-3 нарушений с цитатой и рекомендацией.

## 12. Пять таблиц Analyzer

```text
analyzer.dialogs
analyzer.analysis_tasks
analyzer.dialog_reports
analyzer.dashboard_aggregates
analyzer.dashboard_snapshots
```

Не создавать отдельные таблицы:

- utterances;
- metric history;
- weekly reports;
- monthly reports;
- quarterly reports.

История метрик одного менеджера за дату хранится JSONB внутри одной aggregate
строки.

TTL всех данных — `DATA_TTL_DAYS`, по умолчанию 183 дня.

## 13. Состав dashboard

Dashboard строится для всех менеджеров из четырёх ENV-set:

```env
EFS_VIP_KM_MANAGER_IDS=
EFS_AKM_VIP_MANAGER_IDS=
EFS_VIP_DSB_MANAGER_IDS=
EFS_VIP_TFS_MANAGER_IDS=
```

Один менеджер относится ровно к одной роли.

Обработка идёт batch-ами по `DASHBOARD_MANAGER_BATCH_SIZE`. SQL использует
`WHERE manager_id IN (...)`, bulk-upsert и оконные функции. Не допускать N+1.

## 14. Dashboard aggregate

На каждый `(manager_id, aggregate_date)` сохраняются:

- роль;
- dialogs count;
- сумма и количество scores;
- дневные метрики;
- дневные риски;
- rolling 30-day metrics;
- пятничная weekly point;
- квартальные score sum/count;
- накопительная точка месяца.

Повторная сборка даты обновляет существующую строку.

## 15. Квартальный Q-score

Личный Q-score:

```text
сумма final scores диалогов текущего квартала
------------------------------------------------
количество completed диалогов текущего квартала
```

На первом дне квартала без данных результат равен `EMPTY_SCORE_VALUE`, обычно 0.

Командный Q-score — медиана личных квартальных Q-score только менеджеров той же
роли.

Если в роли один менеджер, team median равен его личному Q-score.

## 16. Месячная динамика Q-score

GET возвращает пять последних месяцев, включая текущий:

- октябрь → июнь–октябрь;
- ноябрь → июль–ноябрь.

Для текущего месяца используется накопительный результат по report date.
Отсутствующее значение равно 0.

Q-score не сохраняется по пятницам. Пятница относится только к weekly metrics.

## 17. Rolling 30 days

Для каждой применимой метрики:

```text
percent = count(score=1) / count(all applicable dialogs) × 100
```

Окно — последние 30 календарных дней, включая report date.

Вкладовые метрики считают только диалоги с актуальной темой вкладов.

## 18. Strengths

Условие:

```text
percent >= STRENGTH_MIN_PERCENT
```

По умолчанию порог 80%.

Ранжирование:

1. больше passed;
2. больше percent;
3. code для стабильного порядка.

Возвращается top `STRENGTHS_LIMIT`, обычно top-3.

## 19. Improvements

Условие:

```text
percent < STRENGTH_MIN_PERCENT
```

Ранжирование:

1. критичность;
2. больше failed;
3. меньше percent;
4. code.

Возвращается top `IMPROVEMENTS_LIMIT`, обычно top-3.

## 20. Delta

Берётся rolling-30 значение прошлого рабочего snapshot и текущего:

```text
delta = previousPercent - currentPercent
```

Если dashboard среды показывает результат вторника, previous обычно относится
к понедельнику, current — ко вторнику.

## 21. Weekly popup improvement

В пятницу после 18:00 UTC сохраняются проценты всех метрик за завершённую
неделю.

Подпись периода — понедельник–воскресенье. Фактические коммуникации —
понедельник–пятница.

Popup возвращает четыре последние завершённые недели. Текущая незавершённая
неделя не показывается.

Также возвращаются последние звонки rolling-30 окна, где выбранная метрика
получила `score=0`.

## 22. Client risks

Окно — `RISK_ROLLING_WINDOW_DAYS`, обычно 10 календарных дней.

События группируются:

```text
manager → client EPK → risk code → communications
```

Один клиент может иметь несколько разных рисков. Один риск может повторяться в
нескольких звонках.

Общий уровень клиента определяется максимальной severity:

```text
есть high   → high
иначе medium → medium
иначе        → low
```

Других уровней нет.

Backend возвращает всех клиентов risk-window. Внутри одинакового уровня
бизнес-ранжирования нет. Frontend сам решает, сколько карточек показать.

Popup клиента возвращает по каждому риску:

- код и название;
- severity;
- последнюю цитату;
- последний call ID и время;
- количество уникальных коммуникаций;
- рекомендацию.

## 23. Менеджер без звонков

Для каждого рабочего дня создаётся dashboard snapshot каждого менеджера из
ролевых ENV-set.

Если новых completed диалогов нет:

- персональные блоки копируются из предыдущего snapshot;
- `carried_forward=true`;
- `source_date` указывает источник данных;
- Q-score всё равно пересчитывается, чтобы корректно обработать новый квартал,
  новый месяц и новую team median.

Если истории нет, создаётся нулевая витрина.

## 24. Готовый snapshot

На `(manager_id, report_date)` хранится одна строка с готовыми данными:

- `q_score_block`;
- `client_risks_block`;
- `client_risk_details`;
- `strengths_block`;
- `improvements_block`;
- `improvement_details`;
- `communications_block`;
- source call IDs;
- роль, source date и carried flag.

Первые шесть dashboard GET читают эту одну строку и не выполняют тяжёлую
математику.

## 25. Восемь GET

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

Правила:

- date обязателен;
- backend ищет строго указанную дату;
- отсутствующая витрина даёт 404;
- первые шесть читают `dashboard_snapshots`;
- список коммуникаций читает `dialog_reports` и поддерживает фильтры;
- popup диалога возвращает готовый `report_payload`;
- наружу видны только completed analyses.

## 26. Производительность

- Не использовать `SELECT *` без date/manager/status ограничения.
- Dashboard обрабатывает менеджеров пакетами.
- Используются bulk-upsert.
- Последние звонки менеджеров выбираются оконной SQL-функцией.
- Тяжёлые старые JSONB details очищаются после окончания окна.
- TTL-удаление выполняется batch-ами.
- HTTP-клиент GigaChat и DB engine создаются один раз.
- Семафоры ограничивают pipeline и GigaChat.
- Не создавать бесконечные `create_task`.
- Не загружать историю всех менеджеров в память одним объектом.

## 27. Главные ENV

### PostgreSQL

```text
DB_USER
DB_PASS / DB_PASSWORD
DB_NAME
POSTGRES_HOSTS
POSTGRES_DSN
POSTGRES_POOL_SIZE
POSTGRES_MAX_OVERFLOW
POSTGRES_POOL_RECYCLE_SECONDS
DATA_TTL_DAYS
```

### Менеджеры

```text
ANALYZED_MANAGER_IDS
PROMPT_ANALYZER_MANAGER_IDS
AUDIO_ANALYZER_MANAGER_IDS
FACTOR_ANALYZER_MANAGER_IDS
EFS_VIP_KM_MANAGER_IDS
EFS_AKM_VIP_MANAGER_IDS
EFS_VIP_DSB_MANAGER_IDS
EFS_VIP_TFS_MANAGER_IDS
```

### GigaChat

```text
GIGACHAT_AUTH_URL
GIGACHAT_BASE_URL
GIGACHAT_CREDENTIALS
GIGACHAT_SCOPE
GIGACHAT_MODEL
GIGACHAT_VERIFY_SSL
GIGACHAT_CERT_FILE
GIGACHAT_KEY_FILE
GIGACHAT_TIMEOUT_SECONDS
GIGACHAT_MAX_CONCURRENCY
GIGACHAT_MAX_ATTEMPTS
GIGACHAT_RETRY_BASE_SECONDS
GIGACHAT_TEMPERATURE или GIGACHAT_TOP_P
GIGACHAT_MAX_OUTPUT_TOKENS
GIGACHAT_REPETITION_PENALTY
LOG_LLM_RESPONSES
```

### Worker/dashboard

```text
WORKER_POLL_INTERVAL_SECONDS
WORKER_CLAIM_LIMIT
DIALOG_PIPELINE_CONCURRENCY
MIN_DIALOG_DURATION_SECONDS
CALENDAR_FILTER_ENABLED
DASHBOARD_ENABLED
DASHBOARD_CRON_HOUR_UTC
DASHBOARD_WAIT_INTERVAL_SECONDS
DASHBOARD_MANAGER_BATCH_SIZE
DASHBOARD_CLEANUP_BATCH_SIZE
METRIC_ROLLING_WINDOW_DAYS
RISK_ROLLING_WINDOW_DAYS
STRENGTH_MIN_PERCENT
STRENGTHS_LIMIT
IMPROVEMENTS_LIMIT
LATEST_COMMUNICATIONS_LIMIT
COMMUNICATIONS_MAX_LIMIT
METRIC_FAILED_COMMUNICATIONS_LIMIT
METRIC_WEEKLY_POINTS_LIMIT
CRITICAL_SCORE_CAP
EMPTY_SCORE_VALUE
```

## 28. Что нельзя возвращать в проект

- BTM как источник ролей: роли задаются четырьмя ENV-set.
- Уровень риска `increasing`: допустимы только high, medium, low.
- Старые weekly/monthly/quarterly LLM reports.
- Отдельную таблицу metric history.
- Таблицу dialog utterances.
- LLM-расчёт Q-score и dashboard-процентов.
- Auth/token для текущих manager GET, если отдельно не появится новое требование.
- Промпты внутри Python.
- Пересчёт dashboard во время GET.
- Показ waiting, processing или failed во внешнем API.

## 29. Как отвечать при будущей работе

Перед изменением логики:

1. сопоставь запрос с этим контекстом;
2. укажи, какой из двух процессов меняется;
3. проверь влияние на пять таблиц и восемь GET;
4. не добавляй таблицу, если данные помещаются в существующий JSONB aggregate;
5. не меняй формулу без явного бизнес-требования;
6. новые числа и switches выноси в ENV;
7. сохраняй backward-compatible API, если явно не сказано иначе;
8. отдельно указывай влияние на CPU, RAM, SQL и семафоры;
9. пиши результат простым русским языком без лишней теории.

Главный подробный документ проекта называется `explanation.md`.

