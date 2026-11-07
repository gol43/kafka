# Аналитическое описание AI Q Score

Документ фиксирует **фактическое поведение текущего кода** для системного аналитика. Термины «день» и «время» ниже относятся к UTC, если не указано иное. Единственная работающая LLM — **GigaChat**. Упоминания Audio/FAQ в конфигурации обозначают задел для отдельных внешних анализаторов, а не другую LLM в текущем контуре. Контракты и нюансы, требующие отдельного согласования, вынесены в конец.

## 1. Границы системы и данные

```text
Data Cleaner → POST /internal/v1/dialogs/cleaned → dialogs + analysis_tasks
                                        ↓ worker
                           GigaChat: hygiene → deposit → risks
                                        ↓
                            dialog_reports (готовый результат)
                                        ↓ 18:00 UTC, dashboard builder
                    dashboard_aggregates → dashboard_snapshots
                                        ↓
                              8 GET для фронтенда
```

Точка сборки приложения — [app/main.py](app/main.py), настройки — [app/config.py](app/config.py), пример значений — [.env](.env). API-префикс задаёт `APP_API_PREFIX`; в текущем `.env` это `/api/v1.0/ai-q-score`. Идентификатор сотрудника в API дополняется слева нулями до восьми цифр, а во входном сообщении Data Cleaner должен уже содержать ровно восемь цифр.

В PostgreSQL используется схема `copilot_ai_q_score`. Источники данных и назначение таблиц:

| Таблица | Ключ и содержание | Жизненный цикл |
|---|---|---|
| `dialogs` | `call_id`; очищенный текст, входной `source_payload`, менеджер, EPK, рабочая дата, статус | Принимается вместе с задачей; после успешной записи отчёта удаляется; ошибки и неуспевшие живут до TTL |
| `analysis_tasks` | UUID, уникальный `call_id`; `waiting/processing/failed/not_analyzed`, попытки, время захвата | Рабочая очередь в БД. При успехе удаляется вместе с входным диалогом; при ошибке остаётся |
| `dialog_reports` | `call_id`; готовый отчёт, `hygiene_results`, `deposit_results`, `risk_results`, резервные JSONB для audio/factor, оценки, флаги, текст и исходный payload | Источник восьмого GET, списка коммуникаций и расчёта витрины |
| `dashboard_aggregates` | уникальная пара `(manager_id, aggregate_date)`; дневные счётчики и результаты метрик/рисков в JSONB, недельные точки, накопительные квартальные и месячные состояния | Вспомогательный дневной слой, чтобы не перечитывать всю историю звонков |
| `dashboard_snapshots` | уникальная пара `(manager_id, report_date)`; готовые блоки Q-score, рисков, сильных и слабых метрик, детализации | Основной слой чтения GET; по менеджеру берётся самый свежий снимок |

Модели и индексы — [app/database/models.py](app/database/models.py), SQL-операции — [app/database/repositories](app/database/repositories). Код читает отчёты для расчёта **за один целевой день и пачку менеджеров**, а историю агрегатов — за ограниченное окно. Список коммуникаций выбирает только необходимые колонки, с `LIMIT/OFFSET`. Индексы поддерживают выборку по `manager_id`, датам и статусам; `dialog_reports` имеет отдельные индексы для менеджера/рабочего дня, клиента и времени. Это проектная организация запросов, а не обещание конкретного времени ответа: измеренной гарантии 10 секунд в коде нет.

### Статусы и полнота результата

`waiting` — задача сохранена; `processing` — захвачена worker; `failed` — один из обязательных этапов не завершён; `not_analyzed` — закрыта при построении витрины без отчёта. Наружу в пользовательские GET попадают только готовые строки `dialog_reports` либо построенные снимки. Результат одного звонка атомарен: если один из трёх GigaChat-блоков не дал допустимого результата, готовый отчёт по нему не создаётся. Повтор `failed` запускается отдельной ручкой, сам worker автоматически её не подбирает.

## 2. Процесс A: один диалог от Data Cleaner до отчёта

### 2.1. Входной контракт

`POST /api/v1.0/ai-q-score/internal/v1/dialogs/cleaned`, `Content-Type: application/json`; [маршрут](app/api/callbacks.py), [Pydantic-схема](app/schemas/dialogs.py). Успешный приём, дубликат и фильтрация возвращают **202 без тела**. Ошибка структуры/бизнес-проверки — 422. Отсюда следует, что 202 само по себе не доказывает создание задачи: проверять следует БД или логи с `call_id`.

| Поле | Тип, обязательность | Значение |
|---|---|---|
| `call_id` | строка 1–64, да | Уникальный ключ звонка и отчёта |
| `manager_id` | строка из ровно 8 цифр, да | Табельный номер; должен присутствовать в конфиге |
| `manager_name` | непустая строка, да | ФИО сотрудника |
| `client_epk` | строка 1–128, да | Устойчивый идентификатор клиента для группировки рисков |
| `client_fio` | строка, нет | Отображаемое ФИО; при отсутствии в ответах пустая строка |
| `duration_seconds` | целое ≥0, да | Основание отсечения коротких звонков |
| `occurred_at` | дата-время ISO 8601, нет | Время разговора для отображения и сортировки; календарная маршрутизация при включённом фильтре опирается на **время поступления** |
| `channel` | строка, нет | Канал источника; пользовательский тип в GET сейчас всегда `call` |
| `participants` | массив, да | Участники, роли `employee`/`client` и, если есть, `employee_id` |
| `cleaned_text` | непустая строка, да | Текст с разметкой ролей для GigaChat; отдельная колонка БД |
| `utterances` | массив, да | Структурные реплики для будущего аудио-анализа: порядок, роль, текст, нормализованный текст, начало/конец в мс, необязательные эмоции/слова |
| `source_metadata` | объект, нет | Метаданные Data Cleaner |
| `encrypted` | `false`, нет | Текущий контракт принимает нешифрованный текст |

Для каждой реплики обязательны `sequence_number`, `speaker_role`, `text`, `normalized_text`, `start_ms`, `end_ms`; допускаются `speaker_id`, `channel`, `eou`, `eou_reason`, `main_speaker_confidence`, `emotions` с девятью оценками и `word_alignments` со словом и границами в мс. Нет обязательных `contract_version`/`cleaner_version`. Входной payload хранится JSONB без дублирования `cleaned_text`; роли/таймкоды/эмоции сохраняются для будущего использования. Нормативный контракт — схема Python.

Минимальный самодостаточный пример сообщения Data Cleaner (время приёма, календарный фильтр и списки менеджеров всё равно определяют, будет ли оно сохранено):

```http
POST /api/v1.0/ai-q-score/internal/v1/dialogs/cleaned
Content-Type: application/json

{
  "call_id": "dc-20261106-001",
  "manager_id": "00000001",
  "manager_name": "Иван Иванов",
  "client_epk": "K001",
  "client_fio": "Петров Пётр Петрович",
  "duration_seconds": 90,
  "occurred_at": "2026-11-06T12:30:00Z",
  "channel": "phone",
  "participants": [
    {"role": "employee", "name": "Иван Иванов", "employee_id": "00000001"},
    {"role": "client", "name": "Петров Пётр Петрович"}
  ],
  "cleaned_text": "Сотрудник: Здравствуйте. Клиент: Я хочу закрыть счёт и уйти в другой банк.",
  "utterances": [
    {"sequence_number": 1, "speaker_role": "employee", "text": "Здравствуйте.", "normalized_text": "Здравствуйте.", "start_ms": 0, "end_ms": 1000},
    {"sequence_number": 2, "speaker_role": "client", "text": "Я хочу закрыть счёт и уйти в другой банк.", "normalized_text": "Я хочу закрыть счёт и уйти в другой банк.", "start_ms": 1100, "end_ms": 3500}
  ],
  "source_metadata": {"source": "data-cleaner"},
  "encrypted": false
}
```

### 2.2. Приём и календарь

Порядок в [dialog_intake.py](app/services/dialog_analysis/dialog_intake.py): проверка `duration_seconds >= MIN_DIALOG_DURATION_SECONDS` (по умолчанию 50), календарное назначение `work_date`, проверка менеджера и анализаторов, проверка дубликата, транзакционная запись `dialogs` и `analysis_tasks` со статусом `waiting`. Всё отфильтрованное **не записывается**. Время `occurred_at` не определяет рабочую дату при `CALENDAR_FILTER_ENABLED=true`.

Календарное правило находится в [calendar_policy.py](app/services/dialog_analysis/calendar_policy.py): с понедельника по четверг до 18:00 UTC звонок относится к текущему дню, начиная с 18:00 — к следующему; пятница после 18:00 и вся суббота отсекаются; воскресенье до 18:00 отсекается, после 18:00 назначается на понедельник. Пятница до 18:00 относится к пятнице. Если `CALENDAR_FILTER_ENABLED=false`, рабочая дата берётся из `occurred_at` (или времени приёма). Порог календаря в этом модуле сейчас зафиксирован числом 18 и **не меняется** вслед за `DASHBOARD_CRON_HOUR_UTC`.

`ANALYZED_MANAGER_IDS` определяет допустимых сотрудников, `PROMPT_ANALYZER_MANAGER_IDS` обязателен для каждого допущенного. Четыре `EFS_..._MANAGER_IDS` задают ровно одну роль каждому сотруднику и команду для медианы. Конфигурация проверяет пересечения ролей при запуске. Дубликат `call_id` не создаёт вторую задачу.

### 2.3. Worker, GigaChat и ошибки

[analysis_worker.py](app/services/dialog_analysis/analysis_worker.py) раз в `WORKER_POLL_INTERVAL_SECONDS` выбирает ограниченное число `waiting` задач (`WORKER_CLAIM_LIMIT`, не больше `DIALOG_PIPELINE_CONCURRENCY`) с `FOR UPDATE SKIP LOCKED`. Worker берёт допустимую `work_date`: до часа построения — не позже текущей даты, с часа построения — не позже предыдущей календарной даты. Несколько диалогов могут обрабатываться параллельно; семафор pipeline ограничивает их число. Внутри одного диалога [prompt_dialog_analyzer.py](app/services/dialog_analysis/prompt_dialog_analyzer.py) вызывает **последовательно** гигиену → вклады → риски. Три обязательных запроса идут в GigaChat даже тогда, когда тема вкладов отсутствует. При `DEPOSIT_ANALYSIS_ENABLED=false` депозитный блок заменяется техническим `DEPOSIT_TOPIC=0`, без запроса вкладов — это явный конфигурационный режим, не обычный случай.

У всех трёх агентов один экземпляр [GigaChat provider](app/agents/gigachat_provider/gigachat_provider.py) с общим `GIGACHAT_MAX_CONCURRENCY` семафором. При значении 1 одновременно выполняется максимум **одна попытка сетевого запроса на экземпляр приложения**, хотя несколько pipeline могут ждать очереди. Запрос строится по YAML-каталогу блока, требует структурированный JSON с точным набором кодов; у GigaChat нет права опустить `DEPOSIT_TOPIC`, добавить код или дублировать его. Проверяются score 0/1, цитата при `quote_required=true` и её точное присутствие в `cleaned_text`. Для `score=1` и метрики без обязательной цитаты quote приводится к пустому значению. Валидатор повторяет некорректный ответ до `GIGACHAT_VALIDATION_MAX_ATTEMPTS`; сетевые ошибки повторяются отдельно до `GIGACHAT_MAX_ATTEMPTS`. Семафор удерживается только во время каждой сетевой попытки, на паузе между повторами отпускается. Семантика каталога — [app/agents/prompts/criteria](app/agents/prompts/criteria), шаблоны — [app/agents/prompts](app/agents/prompts).

У гигиены 27 критериев Prompt 4Q, у вкладов 13 с техническим `DEPOSIT_TOPIC`, у рисков три. Блоки независимы: риск не зависит от депозитного topic и не влияет на Q-score. `ACTIVE_CRITERIA_CODES` ограничивает текущие критерии гигиены; для депозитов и рисков ожидается полный каталог. Подключённые в конфиге Audio/FAQ будут отдельными внешними анализами, их результаты не относятся к трём запросам GigaChat.

Если какой-либо обязательный этап падает, задача и входной диалог становятся `failed`, `dialog_reports` не появляется. При перезапуске процесса `processing`, у которого `claimed_at` старше `WORKER_STALE_TASK_SECONDS`, восстанавливается в `waiting` при очередном обходе через `WORKER_RECOVERY_INTERVAL_SECONDS`; это не минутный таймаут сам по себе. Ручной `POST /api/v1.0/ai-q-score/analysis/run/dialog` с `{"call_id":"..."}` ставит **failed** задачу на повтор, возвращает 202 или 404. Успех сохраняет полный `dialog_reports` и удаляет исходный диалог и задачу; клиент видит только готовый отчёт.

### 2.4. Балл звонка и готовый payload

Формула в [scoring.py](app/services/dialog_analysis/scoring.py): балл блока = `max(0, 100 − сумма penalty у критериев со score=0)`. Критичный `severity=critical` ограничивает балл блока 80. Если `DEPOSIT_TOPIC=0`, остальные оценки вкладов исключаются из оценки и аналитики, итог звонка равен баллу гигиены, `deposit_score` отсутствует. Если topic=1, итог = округлённое половинами вверх среднее гигиены и вкладов; при критичном нарушении итог дополнительно ограничен `CRITICAL_SCORE_CAP`. `deviationsCount` считает нули гигиены и **применимых** вкладов, риски не считает. `DEPOSIT_TOPIC` не выводится на UI через `UI_HIDDEN_METRIC_CODES`.

[dialog_report_builder.py](app/services/dialog_analysis/dialog_report_builder.py) заранее формирует UI-payload: EPK/ФИО/время/балл/число отклонений; список только выявленных рисков (`score=0`, название и уровень); текст `strengths` по шаблону с максимумом `DIALOG_STRENGTHS_LIMIT` положительных метрик; до `DIALOG_IMPROVEMENTS_LIMIT` отрицательных метрик с рекомендацией и допустимой цитатой. Текст сохраняется один раз в БД, повторный GET его не генерирует. Исходные три набора ответов GigaChat также хранятся в JSONB для аудита и последующей агрегации.

## 3. Процесс B: ежедневная сборка дашборда

### 3.1. Запуск, 18:00 и 18:30

[dashboard_scheduler.py](app/services/dashboard/dashboard_scheduler.py) по `DASHBOARD_ENABLED=true` ставит cron каждый день в `DASHBOARD_CRON_HOUR_UTC:00` UTC; суббота/воскресенье автоматически пропускаются. Та же логика запускается ручной `POST /api/v1.0/ai-q-score/analysis/run/dashboard?date=YYYY-MM-DD`. Без `date` берётся текущий день UTC. Ручная сборка за выходной допустима только при `CALENDAR_FILTER_ENABLED=false`. PostgreSQL advisory lock не допускает одновременной сборки несколькими экземплярами.

В момент сборки проверяются **только `processing` задачи целевого дня, захваченные до cutoff**. Если они есть и ещё не истекли `DASHBOARD_ANALYSIS_GRACE_SECONDS` (по умолчанию 1800), процесс спит **до 18:30**, затем все оставшиеся `waiting/processing` целевого дня переводит в `not_analyzed` и строит витрину из готовых отчётов. Если processing не было, `waiting` закрываются сразу в 18:00 и сборка не откладывается. Это не цикл, который завершает ожидание досрочно, когда processing закончились. Задачи, закрытые `not_analyzed`, не создают отчёт. Worker не должен показывать такой звонок в GET.

### 3.2. Какие менеджеры и какие записи читаются

[dashboard_builder.py](app/services/dashboard/dashboard_builder.py) берёт **все четыре списка ролей** из ENV, даже если у сотрудника не было звонков сегодня: ему строится снимок с сохранением накопленного квартального результата. Не берётся произвольный менеджер вне этих списков. Пачка ограничена `DASHBOARD_MANAGER_BATCH_SIZE` (по умолчанию 50). Для даты D из `dialog_reports` выбираются отчёты этой `work_date` нужной пачки, затем предыдущий агрегат менеджера, пятничная история текущей недели, ограниченная история агрегатов и последний снимок для месячной шкалы. Сначала upsert `dashboard_aggregates`, затем расчёт командных медиан по всем ролям, затем upsert `dashboard_snapshots`. Уникальные пары менеджер+дата делают ручной повтор пересборкой дня, а не вторым снимком.

### 3.3. Q-score

По каждому готовому диалогу берётся `score` из `dialog_reports`. Дневной агрегат: `dialogScoreSum = сумма score`, `dialogScoreCount = число готовых диалогов`. Квартальное состояние накапливает обе величины до смены квартала. `personal = int(quarter.scoreSum / quarter.dialogCount)`; при нулевом знаменателе 0. Здесь `int` отбрасывает дробную часть. Выходные и отпуск не добавляют звонков и не снижают оценку. Команда — **медиана текущих личных квартальных Q-score всех сотрудников той же роли**, включая сотрудников без диалогов с нулевым значением; значение `.5` округляется вверх. Это не среднее арифметическое по команде. Месячный счётчик считается таким же отношением суммы баллов к числу диалогов с обнулением при новом месяце. `months` содержит четыре месяца: текущий и три предыдущих, включая заполнители с 0. Источник формул — [q_score.py](app/services/dashboard/calculations/q_score.py).

### 3.4. Риски

Дневные `risk_results` включают только `score=0`, сохраняют EPK, ФИО, код, заголовок, `high/medium/low`, цитату, рекомендацию, call ID и время. Окно — последние `RISK_ROLLING_WINDOW_DAYS` **календарных** дней, включая D; в `.env` 10. Группировка: менеджер → EPK → код риска. Для каждого кода число повторений — число разных `call_id`, цитата/рекомендация/заголовок — из последнего выявления. У клиента может быть несколько рисков, итоговый уровень клиента — максимальный `high > medium > low`. GET списка возвращает одну карточку на клиента; сортировка по уровню риска, затем по фамилии/ФИО (пустое ФИО в конце), затем EPK. Детализация возвращает все риски данного EPK. Код — [risks.py](app/services/dashboard/calculations/risks.py) и [certain_client_risk.py](app/services/dashboard/calculations/certain_client_risk.py).

### 3.5. «Получается отлично» и «Нужно улучшить»

По каждому критерию из **применимой** гигиены/вкладов дневной агрегат содержит `passed`, `failed`, `total` и ссылки на звонки с нарушением. Риски здесь не участвуют. Текущий период при стандартном `STRENGTHS_IMPROVEMENTS_PERIOD_DAYS=7`: `[D−6, D]`; предыдущий: `[D−13, D−7]`. Это календарные диапазоны: дни без звонков просто не прибавляют знаменатель. `positivePercent = int(100 × passed / total)`, `negativePercent = int(100 × failed / total)`. Если в предыдущем окне нет результатов, его процент = 0. Метрика без результата в текущем окне карточкой не становится. `percent1` — текущий, `percent2` — предыдущий, `delta` — строка со знаком `current−previous` в процентных пунктах.

При `positivePercent >= STRENGTH_MIN_PERCENT` (80) метрика кандидат в Strengths, но дополнительно требуется не менее `STRENGTHS_MIN_SAMPLE_SIZE` (10) применимых диалогов за `STRENGTHS_SAMPLE_WINDOW_DAYS` (30). `STRENGTHS_EXCLUDED_METRIC_CODES` исключает код только из топа Strengths. При `positivePercent < 80` кандидат в Improvements; здесь выводится **доля нарушений**, `failed/total`. Оба блока сортируются по рейтингу и режутся `STRENGTHS_LIMIT`/`IMPROVEMENTS_LIMIT` (3). Формулы рейтинга: `0,6 × (severityRank/3) + 0,4 × log(1+passed)/log(1+total)` для Strengths, аналогично с `failed` для Improvements. Ранги `critical=3`, `significant=2`, `minor=1`, `info=0`; при равном рейтинге — код метрики. Расчёт — [dashboard_history.py](app/services/dashboard/calculations/dashboard_history.py), [strengths.py](app/services/dashboard/calculations/strengths.py), [improvements.py](app/services/dashboard/calculations/improvements.py).

### 3.6. Попап метрики и историчность

Каждую **пятницу** при сборке создаётся недельная точка с `periodStart=понедельник`, `periodEnd=воскресенье`; в числителе нарушения понедельника–пятницы, в знаменателе применимые диалоги этих дней. Выходные входят только в подпись периода. Если знаменатель 0, процент 0. Для метрик из текущего топа Improvements детализация выбирает до `CERTAIN_IMPROVEMENT_PERIODS_LIMIT` (4) последних сохранённых недельных точек, от новой к старой, и до `CERTAIN_IMPROVEMENT_COMMUNICATIONS_LIMIT` (5) последних звонков с `score=0`. В ответе по неделе только `periodStart`, `periodEnd`, `percent`; по звонку `callId`, `type`, `clientEpk`, `occurredAt`. Источник — [certain_improvement_metric.py](app/services/dashboard/calculations/certain_improvement_metric.py).

Каждый агрегат хранит компактную дневную статистику, недельную точку и накопительные квартальные/месячные суммы. `compact_history` обнуляет старые подробные JSONB рисков/метрик за пределами нужных окон, сохраняя строку и накопительные состояния. Это снижает повторное чтение `dialog_reports`, однако итоговые `dashboard_snapshots` остаются отдельными дневными готовыми ответами. Ограничение: текущая загрузка истории — максимум из 30, 10 и `4×7=28` дней; для вторника–четверга четвёртая прошлая пятничная точка может оказаться старше 30 дней и отсутствовать. Это следует считать открытым дефектом требования «всегда четыре недели».

## 4. Процесс C: восемь GET для фронтенда

Все примеры используют `BASE=http://localhost:8082/api/v1.0/ai-q-score`. `date` для этих GET **не передаётся**: читается последний сформированный snapshot менеджера. Исключение — восьмой GET, который по `call_id` читает готовый отчёт. Схемы типов и обязательности — [app/schemas/dashboard.py](app/schemas/dashboard.py), маршруты — [app/api/manager.py](app/api/manager.py), чтение — [manager_service.py](app/services/dashboard/manager_service.py). В JSON используются `camelCase` имена. При отсутствии снимка/детализации — 404, при неправильном manager ID — 400. Данных с `null` наружу не планируется: сервис заменяет `None` на пустую строку, оценки/списки по умолчанию 0/`[]`.

| № | GET пример | Источник и ответ |
|---|---|---|
| 1 | `GET $BASE/manager/00000001/q-score` | Из `dashboard_snapshots.q_score`: `{"personal":76,"teamMedian":79,"months":[{"year":2026,"month":11,"qScore":76},...]}`; ровно четыре месяца |
| 2 | `GET $BASE/manager/00000001/client-risks` | Из `risks`: `{"items":[{"clientEpk":"K001","clientFio":"Иванов Иван Иванович","level":"high"}]}`; все клиенты окна, без backend лимита |
| 3 | `GET $BASE/manager/00000001/client-risks/K001` | Из `certain_client_risks[K001]`: `clientEpk`, `clientFio`, общий `level`, `risks:[{metricCode,title,level,quote,count,recommendation}]`; 404, если EPK нет в последнем снимке |
| 4 | `GET $BASE/manager/00000001/strengths` | Из `strengths`: `{"items":[{"metricCode":"HYG_01","title":"...","percent1":90,"percent2":80,"delta":"+10"}]}`; до 3 |
| 5 | `GET $BASE/manager/00000001/improvements` | Из `improvements`: те же поля карточки; здесь проценты — доля нулей, `title` негативный, до 3. Рекомендация не входит в публичную схему этого GET |
| 6 | `GET $BASE/manager/00000001/improvements/HYG_01` | Из `certain_improvement_metrics[code]`: `metricCode`, `title`, `recommendation`, `periods:[{periodStart,periodEnd,percent}]`, `communications:[{callId,type,clientEpk,occurredAt}]`; 404 вне готовой детализации |
| 7 | `GET $BASE/manager/00000001/dialogs?score=low&client_epk=K001&date_from=2026-11-01&date_to=2026-11-07&offset=0&limit=5` | Проекция из `dialog_reports`, только `work_date <= дата последнего snapshot`; `{"items":[{"callId":"dc-1","type":"call","clientEpk":"K001","occurredAt":"...","score":39}],"hasMore":false}` |
| 8 | `GET $BASE/manager/dialogs/dc-1` | Сохранённый `dialog_reports.report_payload`: `callId`, `clientEpk`, `clientFio`, `occurredAt`, `type`, `score`, `deviationsCount`, `risks`, `strengths` (строка), `improvements` (до 5 объектов) |

Для №7 фильтры необязательны: `score=low|medium|high` означает соответственно `0–40`, `41–79`, `80–100` **баллов звонка**, это не уровень клиентского риска; `client_epk` — точное совпадение; `date_from/date_to` — включительные календарные даты по `occurred_at` UTC; `offset≥0`, `limit` по умолчанию `LATEST_COMMUNICATIONS_LIMIT=5`, максимум `COMMUNICATIONS_MAX_LIMIT=100`. Сортировка `occurred_at DESC`; выбирается `limit+1` для `hasMore`. Сервис не читает JSONB большого отчёта для каждого элемента списка. №8 запрашивается только по `call_id`, без `manager_id` и без привязки к дате snapshot; значит доступность нового отчёта там не зависит от ночной сборки. Авторизацию и разграничение доступа нужно обеспечивать внешним контуром: в данном маршруте проверки принадлежности call ID менеджеру нет.

Полные формы ответов восьми GET (значения иллюстративны, имена и типы полей соответствуют текущей схеме):

```json
1  {"personal":76,"teamMedian":79,"months":[{"year":2026,"month":11,"qScore":76},{"year":2026,"month":10,"qScore":82},{"year":2026,"month":9,"qScore":0},{"year":2026,"month":8,"qScore":0}]}
2  {"items":[{"clientEpk":"K001","clientFio":"Петров Пётр Петрович","level":"high"}]}
3  {"clientEpk":"K001","clientFio":"Петров Пётр Петрович","level":"high","risks":[{"metricCode":"RISK_01","title":"Намерение прекратить обслуживание","level":"high","quote":"Я хочу уйти в другой банк","count":2,"recommendation":"Связаться с клиентом"}]}
4  {"items":[{"metricCode":"HYG_01","title":"Приветствие","percent1":90,"percent2":80,"delta":"+10"}]}
5  {"items":[{"metricCode":"HYG_02","title":"Не согласован следующий шаг","percent1":40,"percent2":25,"delta":"+15"}]}
6  {"metricCode":"HYG_02","title":"Не согласован следующий шаг","recommendation":"Согласовать следующий шаг с клиентом","periods":[{"periodStart":"2026-11-02","periodEnd":"2026-11-08","percent":40}],"communications":[{"callId":"dc-20261106-001","type":"call","clientEpk":"K001","occurredAt":"2026-11-06T12:30:00Z"}]}
7  {"items":[{"callId":"dc-20261106-001","type":"call","clientEpk":"K001","occurredAt":"2026-11-06T12:30:00Z","score":39}],"hasMore":false}
8  {"callId":"dc-20261106-001","clientEpk":"K001","clientFio":"Петров Пётр Петрович","occurredAt":"2026-11-06T12:30:00Z","type":"call","score":39,"deviationsCount":2,"risks":[{"code":"RISK_01","title":"Намерение прекратить обслуживание","severity":"high"}],"strengths":"Вы хорошо выполнили следующие критерии: приветствие.","improvements":[{"code":"HYG_02","title":"Не согласован следующий шаг","severity":"significant","recommendation":"Согласовать следующий шаг с клиентом","quote":""}]}
```

Это восемь **отдельных JSON-объектов**, помеченных номером маршрута, а не один JSON-документ. Примеры рекомендаций и заголовков здесь только показывают форму; фактический текст берётся из YAML-критерия, и аналитик должен сверять его с актуальным каталогом.

## 5. Процесс D: конфигурация, хранение и операции

Настройки загружаются при старте через [Settings](app/config.py) из окружения/`.env` и не пересчитываются на каждом GET. При переносе в ConfigMap переменные имеют те же имена; секреты БД и GigaChat нужно подавать отдельно как окружение/Secret. Все переменные текущего `.env` перечислены ниже по назначению.

| Группа | Переменные | Влияние |
|---|---|---|
| API | `APP_NAME`, `APP_API_PREFIX` | Имя сервиса и префикс маршрутов |
| Логи | `LOGGER_DEBUG`, `LOGGER_LEVEL`, `LOG_FILE_HANDLER_ENABLED`, `LOG_MAX_BYTES`, `LOG_BACKUP_COUNT`, `LOG_TOTAL_SIZE_CAP`, `LOG_PATH`, `CONTEXT_VARS`, `JSON_MDC_MAPPING`, `LOG_LLM_RESPONSES` | Уровень/файл/ротация, MDC request/call/manager, логирование ответа GigaChat |
| Наблюдаемость и аудит | `MANAGEMENT_PORT`, `PROMETHEUS_PATH`, `AUDIT_BOOTSTRAP_SERVERS`, `AUDIT_METAMODEL_TOPIC`, `AUDIT_EVENT_TOPIC` | Технический HTTP/Prometheus и параметры аудита; не участвуют в Q-score |
| PostgreSQL | `DB_NAME`, `DB_USER`, `DB_PASS`, `POSTGRES_HOSTS`, `POSTGRES_POOL_SIZE`, `POSTGRES_MAX_OVERFLOW`, `POSTGRES_POOL_RECYCLE_SECONDS`, `DB_AUTO_CREATE_SCHEMA` | DSN, лимиты соединений, локальное создание схемы; `POSTGRES_HOSTS` допускает несколько master-адресов |
| GigaChat | `GIGACHAT_BASE_URL`, `GIGACHAT_SCOPE`, `GIGACHAT_MODEL`, `GIGACHAT_VERIFY_SSL`, `GIGACHAT_CERT_FILE`, `GIGACHAT_KEY_FILE`, `GIGACHAT_TIMEOUT_SECONDS`, `GIGACHAT_TEMPERATURE` | Endpoint, модель и TLS, таймаут/стабильность ответа |
| GigaChat: нагрузка/повторы | `GIGACHAT_MAX_CONCURRENCY`, `GIGACHAT_MAX_ATTEMPTS`, `GIGACHAT_RETRY_BASE_SECONDS`, `GIGACHAT_VALIDATION_MAX_ATTEMPTS`, `GIGACHAT_VALIDATION_RETRY_SECONDS` | Общий на процесс семафор и раздельные сетевые/валидационные повторы; лимит на несколько реплик приложения отдельно глобально не координируется |
| Сотрудники | `ANALYZED_MANAGER_IDS`, `PROMPT_ANALYZER_MANAGER_IDS`, `AUDIO_ANALYZER_MANAGER_IDS`, `FAQ_ANALYZER_MANAGER_IDS`, `EFS_VIP_KM_MANAGER_IDS`, `EFS_VIP_AKM_MANAGER_IDS`, `EFS_VIP_DSB_MANAGER_IDS`, `EFS_VIP_TFS_MANAGER_IDS` | Допуск звонков, назначение анализаторов и взаимоисключающие роли для командной медианы |
| Будущие внешние сервисы | `AUDIO_ANALYZER_URL`, `FAQ_ANALYZER_URL`, `EXTERNAL_ANALYZER_TIMEOUT_SECONDS` | Адрес/таймаут отдельных audio/factor интеграций при их включении |
| Вход и worker | `WORKER_POLL_INTERVAL_SECONDS`, `WORKER_CLAIM_LIMIT`, `WORKER_STALE_TASK_SECONDS`, `WORKER_RECOVERY_INTERVAL_SECONDS`, `DIALOG_PIPELINE_CONCURRENCY`, `MIN_DIALOG_DURATION_SECONDS`, `CALENDAR_FILTER_ENABLED` | Скорость чтения очереди, восстановление зависших, отсечение коротких, календарь |
| Каталог/оценка | `ACTIVE_CRITERIA_CODES`, `DEPOSIT_ANALYSIS_ENABLED`, `CRITERIA_VERSION`, `PROMPT_VERSION`, `CRITICAL_SCORE_CAP`, `DIALOG_IMPROVEMENTS_LIMIT`, `UI_HIDDEN_METRIC_CODES` | Состав гигиены, депозитный режим, версия результата, критичный потолок и отображение |
| Сборка/очистка | `DASHBOARD_ENABLED`, `DASHBOARD_CRON_HOUR_UTC`, `DASHBOARD_ANALYSIS_GRACE_SECONDS`, `DASHBOARD_MANAGER_BATCH_SIZE`, `DASHBOARD_CLEANUP_BATCH_SIZE`, `DATA_CLEANUP_INTERVAL_MINUTES`, `DATA_TTL_DAYS`, `EMPTY_SCORE_VALUE` | Cron, ожидание, размер пачки, фоновая очистка и нулевое значение |
| Метрики | `STRENGTHS_IMPROVEMENTS_PERIOD_DAYS`, `METRIC_HISTORY_DAYS`, `STRENGTH_MIN_PERCENT`, `STRENGTHS_MIN_SAMPLE_SIZE`, `STRENGTHS_SAMPLE_WINDOW_DAYS`, `STRENGTHS_EXCLUDED_METRIC_CODES`, `STRENGTHS_LIMIT`, `DIALOG_STRENGTHS_LIMIT`, `IMPROVEMENTS_LIMIT`, `CERTAIN_IMPROVEMENT_COMMUNICATIONS_LIMIT`, `CERTAIN_IMPROVEMENT_PERIODS_LIMIT` | Два окна, пороги, топы и детализация |
| Риски/список | `RISK_ROLLING_WINDOW_DAYS`, `LATEST_COMMUNICATIONS_LIMIT`, `COMMUNICATIONS_MAX_LIMIT` | Календарное окно риска и постраничный список |
| Тестирование | `TEST_DATA_API_ENABLED` | Включает `POST /analysis/run/dashboard-test-data`, который вставляет фикстуры и вызывает обычный builder; в рабочем окружении следует выключать |

YAML-критерий содержит код, блок, положительный/отрицательный заголовок, определения, правила/примеры, `severity`, `penalty`, требование цитаты и рекомендацию. Метрика score=1 означает соблюдение, score=0 — нарушение или выявленный риск. У risk критериев уровни `high/medium/low`, у качества `critical/significant/minor/info`. Рекомендации и названия не генерируются при GET: они берутся из каталогов при анализе и сохраняются. Технический `DEPOSIT_TOPIC` участвует в маршрутизации оценки, но не показывается. Положительный текст одного диалога берётся из отдельного набора шаблонов, не генерируется GigaChat.

`DATA_TTL_DAYS=183` — приблизительно шесть месяцев, не календарное «вычесть 6 месяцев». При записи каждой сущности устанавливается `expires_at`; отдельный interval job запускается при старте и затем каждые `DATA_CLEANUP_INTERVAL_MINUTES`, удаляет порциями по `DASHBOARD_CLEANUP_BATCH_SIZE`. Поэтому физическое удаление может отставать от `expires_at` до следующего прохода; данные в пяти таблицах удаляются независимо. Готовый отчёт удаляется по собственному сроку, а исходный диалог и задача при успехе удаляются намного раньше. История с уже удалёнными отчётами остаётся в снимках только до их собственного TTL.

### Пример сквозного движения

Диалог `call_id=dc-001`, `manager_id=00000001`, `client_epk=K001`, принятый во вторник 17:59 UTC и длительностью 90 секунд, получает `work_date=вторник`, две строки `waiting`. Worker захватывает задачу, последовательно получает hygiene, deposit topic+метрики, risks; допустим, тема вклада отсутствует, риск ухода score=0, в гигиене одно нарушение. Тогда балл определяется только гигиеной, риск хранится отдельно, отсутствующие вклады не создают штраф и не попадают в карточки. В транзакции появляется `dialog_reports`, вход и задача удаляются. Если анализ закончился к сборке, во вторничный агрегат добавятся балл, нарушение и риск; snapshot получит квартальный балл, риск за 10 дней и статистику окон. В среду фронт прочитает последний готовый снимок вторника. Если GigaChat упал, задача останется `failed`, отчёта и UI-объекта не будет. Если к 18:00 задача ещё `processing`, сборка задержится до 18:30; если `waiting`, она закроется сразу при сборке. Звонок, полученный во вторник **после** 18:00, получит рабочую дату среды.

### Зафиксированные ограничения для аналитика

1. Календарь приёма использует константу 18:00, а scheduler — `DASHBOARD_CRON_HOUR_UTC`. При изменении cron следует синхронизировать эти правила в коде.
2. Ожидание processing сейчас длится до полного срока grace; `waiting` сразу закрываются в `not_analyzed`. Это существенно для формулировки SLA и потери поздних звонков.
3. Четыре недельные точки не гарантированы при текущей глубине загрузки агрегатов. Для гарантии потребуется расширить горизонт истории.
4. Сборка читает готовые отчёты по `work_date`, но не фильтрует `completed_at <= cutoff`; ручная пересборка прошедшей даты может включить отчёт, которого не было на исходный момент.
5. GET №8 доступен сразу после анализа и не ограничен датой последнего dashboard snapshot; GET №7 ограничен `work_date` последнего snapshot.
6. `info` критерии с нулевым penalty могут участвовать в статистике метрик, если помечены `included_in_analytics`; это следует согласовать с бизнесом отдельно.
7. При нескольких репликах приложения семафор GigaChat работает **на каждую реплику**. Общий лимит на весь кластер этим кодом не реализован.

