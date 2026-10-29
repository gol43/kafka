# Analyzer: короткий E2E

В Analyzer осталось два процесса:

1. анализ одного диалога;
2. подготовка дневной витрины для восьми GET-ручек.

## Запуск локально

PostgreSQL должен быть доступен на хосте. Порт задаётся через
`POSTGRES_HOST_PORT`, по умолчанию используется `55432`.

```bash
docker compose up -d postgres
docker compose -f docker-compose.analyzer.yml up --build
```

Во втором compose постоянно работают два контейнера: `ollama` и `analyzer`.
`ollama-pull` запускается один раз, скачивает модель и завершается.

Swagger Analyzer: `http://localhost:8082/docs`.

## Путь одного диалога

```text
POST /internal/v1/dialogs/cleaned
  → DialogIntakeService.accept
  → фильтры 50 секунд / manager set / календарь
  → analyzer.dialogs
  → analyzer.analysis_tasks
  → AnalysisWorker
  → hygiene LLM request
  → deposit LLM request
  → risk LLM request
  → Python scoring
  → analyzer.dialog_reports
  → удаление dialogs + completed task
```

Три LLM-запроса выполняются последовательно внутри одного диалога. Несколько
диалогов могут анализироваться параллельно. Все реальные обращения к модели
проходят через общий семафор провайдера.

Риски не влияют на оценку. Вклады влияют на неё только при
`DEPOSIT_TOPIC=1`. Если модель вернула `DEPOSIT_TOPIC=0`, вкладовые критерии
исключаются из Q-score и всех блоков витрины.

## Полный callback без вкладов

```bash
curl.exe -X POST "http://localhost:8082/internal/v1/dialogs/cleaned" -H "Content-Type: application/json" -d "{\"contract_version\":\"1.0\",\"cleaner_version\":\"manual\",\"call_id\":\"manual-general-001\",\"manager_id\":\"00000001\",\"manager_name\":\"Менеджер 1\",\"client_epk\":\"EPK-10001\",\"client_fio\":null,\"duration_seconds\":90,\"occurred_at\":\"2026-10-29T10:00:00Z\",\"channel\":\"phone\",\"participants\":[{\"role\":\"employee\",\"name\":\"Менеджер 1\",\"employee_id\":\"00000001\"},{\"role\":\"client\",\"name\":null}],\"cleaned_text\":\"Сотрудник: Добрый день, меня зовут Анна. Чем могу помочь? Клиент: Хочу уточнить условия обслуживания карты. Сотрудник: Сейчас расскажу и затем отправлю памятку.\",\"utterances\":[],\"source_metadata\":{},\"encrypted\":false}"
```

## Полный callback со вкладом и риском

```bash
curl.exe -X POST "http://localhost:8082/internal/v1/dialogs/cleaned" -H "Content-Type: application/json" -d "{\"contract_version\":\"1.0\",\"cleaner_version\":\"manual\",\"call_id\":\"manual-deposit-001\",\"manager_id\":\"00000001\",\"manager_name\":\"Менеджер 1\",\"client_epk\":\"EPK-20002\",\"client_fio\":null,\"duration_seconds\":120,\"occurred_at\":\"2026-10-29T11:00:00Z\",\"channel\":\"phone\",\"participants\":[{\"role\":\"employee\",\"name\":\"Менеджер 1\",\"employee_id\":\"00000001\"},{\"role\":\"client\",\"name\":null}],\"cleaned_text\":\"Сотрудник: Добрый день, звоню по поводу окончания вашего вклада. Клиент: Меня не устраивает ваша ставка, я уйду в другой банк. Сотрудник: Давайте рассмотрим другой срок и новую ставку.\",\"utterances\":[],\"source_metadata\":{},\"encrypted\":false}"
```

Ответ `202` означает только приём callback. Через worker отчёт появится в
`analyzer.dialog_reports`.

## Получение результата диалога

```bash
curl.exe "http://localhost:8082/manager/dialogs/manual-general-001"
curl.exe "http://localhost:8082/manager/dialogs/manual-deposit-001"
```

Пока полного результата нет либо анализ завершился ошибкой, GET возвращает
`404`. Наружу видны только завершённые отчёты.

## Построение витрины вручную

После завершения анализов:

```bash
curl.exe -X POST "http://localhost:8082/analysis/run/dashboard?date=2026-10-29"
```

В production тот же процесс запускается в `18:00 UTC`. Перед расчётом он ждёт
все `waiting/processing` задачи этого дня, полученные до cutoff. Failed-задачи
не блокируют расчёт и в витрину не входят.

## Восемь GET

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

`date` обязательна. Первые шесть ручек читают один готовый snapshot. Список и
карточка диалога читают `dialog_reports`.

## Пять таблиц

```text
analyzer.dialogs                 вход до успешного анализа
analyzer.analysis_tasks          персистентная очередь worker-а
analyzer.dialog_reports          готовые отчёты отдельных звонков
analyzer.dashboard_aggregates    дневная/30-дневная/недельная математика JSONB
analyzer.dashboard_snapshots     готовые данные восьми блоков JSONB
```

TTL всех данных — 183 дня. Успешные `dialogs` и `analysis_tasks` удаляются
сразу. Failed-задачи остаются для диагностики и ручного повтора:

```bash
curl.exe -X POST "http://localhost:8082/analysis/run/dialog" -H "Content-Type: application/json" -d "{\"call_id\":\"manual-deposit-001\"}"
```

## Где смотреть логи

```bash
docker compose -f docker-compose.analyzer.yml logs -f analyzer ollama
```

Основная последовательность Analyzer:

```text
Dialog callback received
Dialog saved
Dialog task created
Tasks claimed
Task started
Dialog analysis started
Agent started name=prompt
LLM response body=...
Dialog result saved
Task completed
```
