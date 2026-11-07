# Контракт Data Cleaner → AI Q-Score Analyzer

## Endpoint

```http
POST /api/v1.0/ai-q-score/internal/v1/dialogs/cleaned
Content-Type: application/json
```

Версии контракта и Data Cleaner намеренно не передаются. Идемпотентность обеспечивается уникальным `call_id`.

## Обязательные поля

| Поле | Тип | Требование |
|---|---|---|
| `call_id` | string | Уникальный идентификатор, 1–64 символа |
| `manager_id` | string | Ровно восемь цифр |
| `manager_name` | string | Непустое имя менеджера |
| `client_epk` | string | Идентификатор клиента, 1–128 символов |
| `duration_seconds` | integer | Длительность звонка, `>= 0` |
| `participants` | array | Участники звонка |
| `cleaned_text` | string | Непустой очищенный текст с ролями |
| `utterances` | array | Структурированные реплики |
| `encrypted` | boolean | Только `false` |

## Необязательные поля

| Поле | Тип | Поведение при отсутствии |
|---|---|---|
| `client_fio` | string | В БД сохраняется пустая строка |
| `occurred_at` | datetime | Используется время получения Analyzer-ом |
| `channel` | string | Сохраняется без интерпретации |
| `source_metadata` | object | Сохраняется пустой объект |

Дата и время должны передаваться в ISO 8601 с часовым поясом, предпочтительно UTC: `2026-11-07T12:30:00Z`.

## Participant

```json
{
  "role": "employee",
  "name": "Иван Иванов",
  "phone_number": "+79990000000",
  "employee_id": "00000001"
}
```

`role`: `employee`, `client` или `unknown`. Остальные поля необязательны.

## Utterance

```json
{
  "sequence_number": 1,
  "speaker_role": "employee",
  "speaker_id": 1,
  "channel": 1,
  "text": "Добрый день, меня зовут Иван.",
  "normalized_text": "Добрый день, меня зовут Иван.",
  "start_ms": 0,
  "end_ms": 1800,
  "eou": true,
  "eou_reason": "silence",
  "main_speaker_confidence": 0.99,
  "emotions": {
    "positive": 0.7,
    "neutral": 0.2,
    "negative": 0.1,
    "positive_a": 0.7,
    "neutral_a": 0.2,
    "negative_a": 0.1,
    "positive_t": 0.7,
    "neutral_t": 0.2,
    "negative_t": 0.1
  },
  "word_alignments": [
    {"word": "Добрый", "start_ms": 0, "end_ms": 700}
  ]
}
```

Обязательны: `sequence_number`, `speaker_role`, `text`, `normalized_text`, `start_ms`, `end_ms`. Эмоции, word alignment и остальные технические признаки необязательны.

## Полный запрос

```bash
curl -X POST "http://localhost:8082/api/v1.0/ai-q-score/internal/v1/dialogs/cleaned" \
  -H "Content-Type: application/json" \
  -d '{
    "call_id": "dc-test-0001",
    "manager_id": "00000001",
    "manager_name": "Иван Иванов",
    "client_epk": "123456789",
    "client_fio": "Петров Пётр Петрович",
    "duration_seconds": 90,
    "occurred_at": "2026-11-07T12:30:00Z",
    "channel": "phone",
    "participants": [
      {"role": "employee", "name": "Иван Иванов", "employee_id": "00000001"},
      {"role": "client", "name": "Петров Пётр Петрович"}
    ],
    "cleaned_text": "Сотрудник: Добрый день, меня зовут Иван. Клиент: Добрый день.",
    "utterances": [
      {
        "sequence_number": 1,
        "speaker_role": "employee",
        "speaker_id": 1,
        "channel": 1,
        "text": "Добрый день, меня зовут Иван.",
        "normalized_text": "Добрый день, меня зовут Иван.",
        "start_ms": 0,
        "end_ms": 1800,
        "eou": true,
        "eou_reason": "silence",
        "main_speaker_confidence": 0.99,
        "emotions": {
          "positive": 0.7,
          "neutral": 0.2,
          "negative": 0.1,
          "positive_a": 0.7,
          "neutral_a": 0.2,
          "negative_a": 0.1,
          "positive_t": 0.7,
          "neutral_t": 0.2,
          "negative_t": 0.1
        },
        "word_alignments": []
      },
      {
        "sequence_number": 2,
        "speaker_role": "client",
        "speaker_id": 2,
        "channel": 2,
        "text": "Добрый день.",
        "normalized_text": "Добрый день.",
        "start_ms": 1900,
        "end_ms": 2600,
        "eou": true,
        "word_alignments": []
      }
    ],
    "source_metadata": {"source": "data-cleaner"},
    "encrypted": false
  }'
```

## Что сохраняет Analyzer

Отдельными колонками сохраняются идентификаторы, длительность, рабочая дата и `cleaned_text`. В `source_payload` JSONB сохраняется остальной структурированный пакет, включая:

- участников;
- utterances;
- эмоции;
- word alignments;
- channel;
- source metadata;
- имя менеджера.

После успешного анализа `source_payload` переносится в `dialog_reports` и доступен будущим Audio/ML-анализаторам. Срок хранения определяется `DATA_TTL_DAYS`.

## Ответы и фильтрация

- `202 Accepted` — payload прошёл HTTP/Pydantic-валидацию. Это не означает, что GigaChat уже завершил анализ.
- `422` — нарушен JSON-контракт.
- Диалог короче `MIN_DIALOG_DURATION_SECONDS`, менеджер вне списка или диалог вне календарной политики возвращает `202`, но не сохраняется.
- Повторный `call_id` не создаёт второй объект.
