# Data Cleaner

Сервис принимает исходный диалог, **до записи в PostgreSQL шифрует исходный текст**, затем worker очищает текст без LLM и независимо отправляет результат подписчикам. GigaChat в этом сервисе не используется. Основной код разложен по `app/api`, `app/schemas`, `app/services`, `app/database`; словарь и список подписчиков — `app/utils`.

## Запуск

1. Установить зависимости из `requirements.txt`.
2. Выполнить `app/database/migration.sql` в целевой PostgreSQL. Новые таблицы — `copilot_data_cleaner.cleaner_jobs` и `copilot_data_cleaner.callback_deliveries`. Прежняя `anonymization_queue` не используется; её старые задачи автоматически не переносятся.
3. Скопировать `.env.example` в `.env`. Вместо `replace-with-shared-fernet-key` задать действительный ключ Fernet. **Тот же ключ** указать в AI Q Score как `CLIENT_FIO_ENCRYPTION_KEY`. Значения URL должны быть полными адресами POST-ручек.
4. Запустить из корня проекта: `uvicorn app.main:app --host 0.0.0.0 --port 8080`.

`ENCRYPTION_KEY` обязателен: исходный `text`, `utterances[].text`, `normalized_text` и слова в `word_alignments` шифруются до записи в БД. `ENCRYPT_CLIENT_FIO=true` отдельно управляет шифрованием ФИО клиента. Отключение этого флага означает, что ФИО поступит получателю открытым и таким же будет сохранено в очереди; для рабочего контура оставлять `true`.

## Входной POST

Маршрут: `POST /api/v1.0/data-cleaner/anonymize`. Обязательны `call_id` и `text`; остальные поля необязательны для универсального Data Cleaner. **Если включён AI Q Score**, дополнительно нужны `manager_id` (ровно 8 цифр), `client_epk` и `duration_seconds`. Ошибка обязательных полей — 422, принятие — 202. Повтор того же `call_id`, пока задача существует в очереди, не создаёт вторую задачу. После окончательного удаления задачи новый POST с тем же ID будет принят; принимающая сторона должна дедуплицировать по `call_id`.

```json
{
  "call_id": "dc-001",
  "text": "Сотрудник: Добрый день. Клиент: Меня зовут Иван Иванов, переведу деньги в ВТБ.",
  "manager_id": "00000001",
  "client_epk": "K001",
  "client_fio": "Иванов Иван Иванович",
  "duration_seconds": 90,
  "occurred_at": "2026-11-09T10:30:00Z",
  "channel": "phone",
  "utterances": [
    {"sequence_number":1,"speaker_role":"employee","text":"Добрый день.","normalized_text":"Добрый день.","start_ms":0,"end_ms":1000,"emotions":{"neutral":1.0},"word_alignments":[]},
    {"sequence_number":2,"speaker_role":"client","text":"Меня зовут Иван Иванов, переведу деньги в ВТБ.","normalized_text":"Меня зовут Иван Иванов, переведу деньги в ВТБ.","start_ms":1100,"end_ms":4200,"emotions":{"negative":0.7},"word_alignments":[]}
  ],
  "source_metadata": {"source":"external"}
}
```

`utterances` — список реплик в том же формате, который принимает AI Q Score. Data Cleaner сохраняет порядок списка. В каждой реплике очищаются только `text`, `normalized_text` и `word_alignments[].word`; эмоции, роли, таймкоды и другие поля остаются прежними. Вложенные произвольные поля с текстом не очищаются — источник не должен помещать туда персональные данные до согласования схемы. Если входной `text` уже зашифрован тем же ключом, передать `is_encrypted=true`; реплики и ФИО при этом ожидаются открытыми и будут зашифрованы сервисом.

## Очистка и подписчики

`app/services/cleaner.py` загружает `app/utils/elements.yaml` один раз. Регулярные выражения скрывают телефон, карту, email, СНИЛС; затем слова/короткие фразы ищутся по категоризированному словарю. Дата вида `17 декабря` сохраняется; остальные числа заменяются на `#`. Исключения для Сбера не заменяются. Словарь содержит более шести тысяч строк, но **не гарантирует** скрытие неизвестного имени или адреса; источник и ограничения описаны в `app/utils/README.md`.

`app/utils/subscribers.yaml` сопоставляет имя подписчика с контрактом и ENV-переменными полного URL и флага включения. Сейчас доступны контракты:

- `ai_q_score`: JSON с `call_id`, `manager_id`, `client_epk`, `client_fio`, `client_fio_encrypted`, `duration_seconds`, `occurred_at`, `channel`, `cleaned_text`, `utterances`, `source_metadata`. ФИО остаётся зашифрованным до приёма AI Q Score.
- `call_summarization`: только `call_id` и `cleaned_text`.
- `ai_mentor_insight`: динамический callback только для запросов с `callback_url`. Data Cleaner вызывает `callback_url/{call_id}` и передаёт `{"text": "очищенный текст"}`.

Если вход содержит `callback_url`, он маршрутизируется исключительно в AI Mentor Insight и не отправляется в AI Q Score или Call Summarization. Это позволяет принять минимальный контракт из `call_id`, `text`, `callback_url` и `is_encrypted`. Если `callback_url` отсутствует, применяются обычные включённые подписчики AI Q Score и Call Summarization.

Новые типы body добавляются в `AnonymizationWorker._body`. URL не модифицируется и `/{call_id}` к нему не прибавляется. На успешный callback принимается любой HTTP 2xx, включая 202.

## Очередь, ошибки и удаление

`cleaner_jobs` хранит только зашифрованный исходный текст и метаданные; задача `waiting` захватывается как `processing` через `FOR UPDATE SKIP LOCKED`. При успехе за одну транзакцию создаются отдельные `callback_deliveries`, а исходная задача удаляется. При ошибке очистки задача становится `failed` и остаётся до `DATA_TTL_DAYS=183` (около шести месяцев). Worker не повторяет ошибку очистки автоматически.

Каждая доставка имеет собственный статус и счётчик попыток. При 2xx она удаляется. При ошибке повторяется через `CALLBACK_RETRY_SECONDS` до `CALLBACK_MAX_ATTEMPTS`; затем удаляется даже при окончательной неудаче, чтобы БД не росла без конца. Это событие остаётся в логах с `call_id` и именем подписчика. Успех одного подписчика не зависит от отказа другого. После аварийного завершения процесса `processing` старше `WORKER_STALE_SECONDS` снова становится `waiting`. Периодическая очистка удаляет все записи, у которых истёк `expires_at`.

Для AI Q Score в его `.env` нужно задать `CLIENT_FIO_ENCRYPTION_KEY` равным `ENCRYPTION_KEY` Data Cleaner. Отдельный `client_fio_encrypted` относится только к ФИО; общего поля `encrypted` в callback нет.
