# Функциональные и технические требования AI-Q-SCORE

## 1. Блок "Получается отлично" (Strengths)

### 1.1 Назначение блока
Блок возвращает топ-3 метрики, по которым менеджер показал лучший результат (процент выполнения $\ge 80\%$). Показывает динамику выполнения метрик за два скользящих окна.

### 1.2 Формулы
$$\text{positive\_percent\_1} = \left(\frac{\sum (\text{score}=1) \text{ за последние } N \text{ дней}}{\text{total за последние } N \text{ дней}}\right) \times 100$$
$$\text{positive\_percent\_2} = \left(\frac{\sum (\text{score}=1) \text{ за предыдущие } N \text{ дней}}{\text{total за предыдущие } N \text{ дней}}\right) \times 100$$
$$\text{positive\_delta} = \text{positive\_percent\_1} - \text{positive\_percent\_2}$$

Где $N = \text{METRIC\_WINDOW\_SIZE\_DAYS}$ (например, 7 рабочих дней).

**Интерпретация:**
* $100\%$ = все диалоги соответствуют метрике (хорошо)
* $0\%$ = все диалоги не соответствуют метрике (плохо)
* $\text{Delta} > 0$ = улучшение
* $\text{Delta} < 0$ = ухудшение

### 1.3 Пример
| День | Passed ($\text{score}=1$) | Total | Percent |
| :--- | :--- | :--- | :--- |
| Понедельник | 3 | 10 | $30\%$ |
| Вторник | 4 | 10 | $40\%$ |
| Среда | 8 | 10 | $80\%$ |
| Четверг | 6 | 10 | $60\%$ |

* $\text{positive\_percent\_1} = \frac{8+6}{10+10} = 70\%$
* $\text{positive\_percent\_2} = \frac{3+4}{10+10} = 35\%$
* $\text{positive\_delta} = 70 - 35 = +35\%$ (улучшение)

### 1.4 Фильтр "Минимум 10 баллов за 30 дней"
Для попадания в метрики необходимо, чтобы за последние 30 рабочих дней менеджер набрал минимум 10 баллов ($\text{passed}$) по этой метрике:
* $\sum (\text{passed за } 30 \text{ дней}) \ge 10 \implies$ метрика попадает в выборку
* $\sum (\text{passed за } 30 \text{ дней}) < 10 \implies$ метрика исключается

### 1.5 Распределение по блокам
Каждая метрика попадает только в один блок на основе `positive_percent_1`:

| Блок | Condition |
| :--- | :--- |
| Получается отлично | $\text{positive\_percent\_1} \ge 80$ |
| Нужно улучшить | $\text{positive\_percent\_1} < 80$ |

### 1.6 Два названия для каждой метрики
У каждой метрики в YAML критериях заданы два названия:
```yaml
code: GENERAL_01
title_positive: "КМ представился"
title_negative: "КМ не представился"
```
* `title_positive` — используется в блоке "Получается отлично"
* `title_negative` — используется в блоке "Нужно улучшить"

**Пример:**
* В "Получается отлично": *"КМ представился" = 90%* $\implies$ в $90\%$ диалогов менеджер представился
* В "Нужно улучшить": *"КМ не представился" = 10%* $\implies$ в $10\%$ диалогов менеджер не представился

### 1.7 Ранжирование (Математика попадания в топ-3)
Рейтинг считается отдельно для каждого блока по единой формуле:
$$\text{rating} = \left(\frac{\text{severity\_level}}{3}\right) \times 0.6 + \left(\frac{\ln(1 + \text{count})}{\ln(1 + \text{total})}\right) \times 0.4$$

**Параметры формулы:**
| Параметр | Описание | Значение |
| :--- | :--- | :--- |
| `severity_level` | Уровень критичности метрики | критичное = 3, существенное = 2, несущественное = 1, info/unknown = 0 |
| `count` | Количество событий | Для "Нужно улучшить" $\implies$ кол-во нарушений (`failed`). Для "Получается отлично" $\implies$ кол-во успешных проверок (`passed`) |
| `total` | Общее количество проверок за окно | Общее количество проверок по метрике |

**Как работает:**
* Первая часть $(\text{severity\_level} / 3) \times 0.6$ (до $0.6$) отвечает за тяжесть нарушения/успеха.
* Вторая часть $(\ln(1 + \text{count}) / \ln(1 + \text{total})) \times 0.4$ (до $0.4$) отвечает за долю событий.
* Логарифм используется для сглаживания пиков при малых выборках.
* Максимальный рейтинг: $0.6 + 0.4 = 1.0$. Минимальный: $0$.

**Сортировка:** по `rating DESC`. В каждый блок попадает топ-3 метрики с наивысшим рейтингом в своей категории.

---

### 1.8 API — Q-SCORE блок
**Метод:** `GET /manager/{manager_id}/q-score`  
**Параметры:** `manager_id` (path), `date` (query, ISO 8601)  
**Ответ:** `{ personal, teamMedian, months }`

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `personal` | int | Q-SCORE менеджера |
| `teamMedian` | int | Медиана команды по роли |
| `months` | Array[object] | Всегда 4 месяца. Если данных нет — `qScore: 0` |

**Элемент массива `months`:**
| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `year` | int | Год |
| `month` | int | Месяц (1-12) |
| `qScore` | int | Среднее дневных Q-Score за месяц (0, если в месяце не было диалогов) |

**Пример ответа:**
```json
{
  "personal": 92,
  "teamMedian": 88,
  "months": [
    {"year": 2026, "month": 10, "qScore": 0},
    {"year": 2026, "month": 9, "qScore": 91},
    {"year": 2026, "month": 8, "qScore": 0},
    {"year": 2026, "month": 7, "qScore": 90}
  ]
}
```

---

### 1.9 Данные в БД
Данные для метрик хранятся в `dashboard_aggregates.daily_metrics` (JSONB).  
Каждый день в `daily_metrics` по каждой метрике хранится:
```json
{
  "HYGIENE_01": {
    "title_positive": "КМ представился",
    "title_negative": "КМ не представился",
    "severity": "info",
    "recommendation": "Приветствовать каждого клиента",
    "passed": 8,
    "failed": 2,
    "total": 10,
    "violations": []
  }
}
```

---

### 1.10 Ежедневный пересчёт
В рамках `DashboardScheduler.rebuild()`:

1. `_build_aggregate_batch()`:
   * `_daily_stats()` — `daily_metrics` (passed, failed, total)
   * `save_aggregates()`
2. `_build_snapshot_batch()`:
   * `_build_metric_blocks(aggregate, manager_history, report_date, settings)`:
     * a. `window1_rows` = daily за последние N дней
     * b. `window2_rows` = daily за предыдущие N дней
     * c. `thirty_days_rows` = daily за 30 дней
     * d. `window1` = $\sum(\text{passed/failed/total})$ за window1
     * e. `window2` = $\sum(\text{passed/failed/total})$ за window2
     * f. `positive_percent_1 = window1.passed / window1.total * 100`
     * g. `positive_percent_2 = window2.passed / window2.total * 100`
     * h. `positive_delta = positive_percent_1 - positive_percent_2`
     * i. `negative_percent_1 = window1.failed / window1.total * 100`
     * j. `negative_percent_2 = window2.failed / window2.total * 100`
     * k. `negative_delta = negative_percent_1 - negative_percent_2`
     * l. Filter: если `thirty_days.passed < 10` $\implies$ исключить метрику
     * m. Распределение: `positive_percent_1 >= 80` $\implies$ Strengths, иначе $\implies$ Improvements
   * `_rank_metrics(cards, settings)`:
     * a. `rating = (severity_level / 3) * 0.6 + (log(1 + count) / log(1 + total)) * 0.4`
     * b. strengths: top-3 по `str_rating DESC` (count = passed)
     * c. improvements: top-3 по `imp_rating DESC` (count = failed)
   * Q-SCORE менеджера (Dashboard):
     * a. Для каждого дня в периоде: `daily_avg = sum_scores_day / count_dialogs_day`
     * b. Итоговый Q-Score = среднее арифметическое всех `daily_avg`
     * c. Дни без диалогов (0 count) полностью игнорируются — выходные, отпуска, праздники не влияют на оценку
   * Q-SCORE диалога (LLM):
     * a. Рассчитывается при анализе: `max(0, 100 - penalty_sum)`
     * b. При критическом нарушении: `min(score, 80.0)`
   * `save_snapshots()`

---

### 1.11 API — Блок "Получается отлично" (Strengths)
**Метод:** `GET /manager/{manager_id}/strengths`  
**Параметры:** `manager_id` (path), `date` (query, ISO 8601)  
**Ответ:** `{ items: Array[Item] }`

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `items` | Array[Item] | Массив из топ-3 метрик |

**Item:**
| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `metricCode` | string | Код метрики |
| `title` | string | Название метрики (`title_positive`) |
| `percent1` | int | Positive % за последние N дней |
| `percent2` | int | Positive % за предыдущие N дней |
| `delta` | string | Разница со знаком (например `"+7"` или `"-3"`) |

**Пример ответа:**
```json
{
  "items": [
    {
      "metricCode": "HYGIENE_01",
      "title": "КМ представился",
      "percent1": 95,
      "percent2": 88,
      "delta": "+7"
    },
    {
      "metricCode": "HYGIENE_02",
      "title": "Соблюдение приветствия",
      "percent1": 92,
      "percent2": 90,
      "delta": "+2"
    },
    {
      "metricCode": "DEPOSIT_01",
      "title": "Менеджер сообщил причину контакта по вкладу",
      "percent1": 88,
      "percent2": 85,
      "delta": "+3"
    }
  ]
}
```

---

### 1.12 API — Клиентские риски
**Метод:** `GET /manager/{manager_id}/client-risks`  
**Параметры:** `manager_id` (path), `date` (query, ISO 8601)  
**Ответ:** `{ items: Array[ClientRisk] }`

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `items` | Array[object] | Список клиентов с рисками |
| `items[].clientEpk` | string | ЭПК клиента |
| `items[].level` | string | Уровень риска: `high`, `medium`, `low` |

**Пример ответа:**
```json
{
  "items": [
    {"clientEpk": "EPK-01", "level": "high"},
    {"clientEpk": "EPK-02", "level": "medium"}
  ]
}
```

---

### 1.13 API — Детали рисков клиента
**Метод:** `GET /manager/{manager_id}/client-risks/{client_epk}`  
**Параметры:** `manager_id` (path), `client_epk` (path), `date` (query, ISO 8601)  
**Ответ:** `{ clientEpk, risks }`

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `clientEpk` | string | ЭПК клиента |
| `risks` | Array[object] | Список рисков за последние 10 дней |
| `risks[].title` | string | Название риска |
| `risks[].level` | string | `high`, `medium`, `low` |
| `risks[].quote` | string | Цитата (null если нет) |
| `risks[].count` | int | Кол-во диалогов с этим риском |
| `risks[].recommendation` | string | Рекомендация |

**Пример ответа:**
```json
{
  "clientEpk": "EPK-01",
  "risks": [
    {
      "title": "Клиент уходит",
      "level": "high",
      "quote": "Я ухожу в другой банк",
      "count": 3,
      "recommendation": "Уточните причину и предложите альтернативу"
    },
    {
      "title": "Отток средств",
      "level": "medium",
      "quote": null,
      "count": 2,
      "recommendation": "Предложите альтернативу для сохранения средств"
    }
  ]
}
```

---

## 2. Блок "Нужно улучшить" (Improvements)

### 2.1 Назначение блока
Блок возвращает топ-3 метрики, по которым менеджер показал худший результат (процент выполнения $< 80\%$). Показывает динамику нарушений за два скользящих окна.

### 2.2 Формулы
$$\text{negative\_percent\_1} = \left(\frac{\sum (\text{score}=0) \text{ за последние } N \text{ дней}}{\text{total за последние } N \text{ дней}}\right) \times 100$$
$$\text{negative\_percent\_2} = \left(\frac{\sum (\text{score}=0) \text{ за предыдущие } N \text{ дней}}{\text{total за предыдущие } N \text{ дней}}\right) \times 100$$
$$\text{negative\_delta} = \text{negative\_percent\_1} - \text{negative\_percent\_2}$$

Где $N = \text{METRIC\_WINDOW\_SIZE\_DAYS}$ (например, 7 рабочих дней).

**Интерпретация:**
* $0\%$ = нарушений нет (хорошо)
* $100\%$ = все диалоги имеют нарушения (плохо)
* $\text{Delta} > 0$ = ухудшение (процент нарушений вырос)
* $\text{Delta} < 0$ = улучшение (процент нарушений упал)

### 2.3 Распределение по блокам
Та же логика, что и в блоке "Получается отлично" — распределение по `positive_percent_1`:

| Блок | Condition |
| :--- | :--- |
| Получается отлично | $\text{positive\_percent\_1} \ge 80$ |
| Нужно улучшить | $\text{positive\_percent\_1} < 80$ |

Метрика не может попасть в оба блока одновременно.

### 2.4 Два названия для каждой метрики
Используется `title_negative` из YAML критерия:

**Пример:**
* В "Нужно улучшить": *"КМ не представился" = 10%* $\implies$ в $10\%$ диалогов менеджер не представился.

### 2.5 Ранжирование (Математика попадания в топ-3)
Используется та же формула, что и для Strengths:
$$\text{rating} = \left(\frac{\text{severity\_level}}{3}\right) \times 0.6 + \left(\frac{\ln(1 + \text{failed})}{\ln(1 + \text{total})}\right) \times 0.4$$
`count = failed` (нарушения) для Improvements.

**Сортировка:** по `rating DESC` — метрики с большей тяжестью и частотой нарушений выше в списке.

### 2.6 API — Блок "Нужно улучшить"
**Метод:** `GET /manager/{manager_id}/improvements`  
**Параметры:** `manager_id` (path), `date` (query, ISO 8601)  
**Ответ:** `{ items: Array[Item] }`

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `items` | Array[Item] | Массив из топ-3 метрик |

**Item:**
| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `metricCode` | string | Код метрики |
| `title` | string | Название метрики (`title_negative`) |
| `percent1` | int | Negative % за последние N дней |
| `percent2` | int | Negative % за предыдущие N дней |
| `delta` | string | Разница со знаком (например `"-5"` или `"+3"`) |

**Пример ответа:**
```json
{
  "items": [
    {
      "metricCode": "HYGIENE_02",
      "title": "КМ не представился",
      "percent1": 15,
      "percent2": 20,
      "delta": "-5"
    },
    {
      "metricCode": "HYGIENE_03",
      "title": "Не озвучена тема звонка",
      "percent1": 25,
      "percent2": 22,
      "delta": "+3"
    }
  ]
}
```

### 2.7 Ежедневный пересчёт
Аналогично блоку "Получается отлично", но:
* Считаем `negative_percent` вместо `positive_percent`
* Ранжирование инвертированное
* Используем `title_negative` для названия

### 2.8 Конфигурация
Та же конфигурация, что и для блока "Получается отлично" (см. раздел 1.11).

---

## 3. Общие правила

### 3.1 Гигиена vs Вклады
| Параметр | Гигиена | Вклады |
| :--- | :--- | :--- |
| Применяется ко всем диалогам | Да | Нет (только когда тема вкладов обсуждалась) |
| `dialogs_count` | Все диалоги менеджера | Диалоги с темой вкладов |
| `positive_percent` | $\sum\text{passed} / \text{total} \times 100$ | $\sum\text{passed} / \text{total} \times 100$ |
| `DEPOSIT_01 (topic_gate)` | Нет | Да — исключается из аналитики |

### 3.2 Backend хранимые данные
В backend хранятся оба состояния для каждой метрики:
* `positive_percent_1`, `positive_percent_2`, `positive_delta`
* `negative_percent_1`, `negative_percent_2`, `negative_delta`

Это позволяет пересчитывать оба блока ежедневно без потери данных.

### 3.3 Связанные API-эндпоинты
| Эндпоинт | Блок | Описание |
| :--- | :--- | :--- |
| `GET /manager/{id}/q-score` | Q-SCORE | Личный Q-SCORE, медиана, история 4 месяцев |
| `GET /manager/{id}/client-risks` | Риски | Список клиентов с рисками (уровень) |
| `GET /manager/{id}/client-risks/{epk}` | Риски клиента | Детализация рисков по клиенту (за 10 дней) |
| `GET /manager/{id}/strengths` | Получается отлично | Топ-3 метрик с best performance (percent1, percent2, delta) |
| `GET /manager/{id}/improvements` | Нужно улучшить | Топ-3 метрик с worst performance (percent1, percent2, delta) |

### 3.4 Рефакторинг структуры метрик
Метрики хранятся в поддиректориях `app/agents/prompts/criteria/` по блокам:
```text
criteria/
├── hygiene/
│   └── hygiene_01.yaml ... hygiene_27.yaml  (коды: HYG_01 ... HYG_27)
├── deposit/
│   └── deposit_01.yaml ... deposit_14.yaml и deposit_topic.yaml
└── risk/
    ├── risk_01.yaml     (уход из банка, high)
    ├── risk_02.yaml     (вывод средств, high)
    └── risk_03.yaml     (выбор конкурента, medium)
```

Каждый YAML-файл содержит полный набор полей метрики без внешних зависимостей:
* `block: hygiene` — маршрутизирует метрику к соответствующему LLM-агенту
* `code` — уникальный идентификатор, используется в ответах API и ключах JSONB-полей БД
* `title_positive` / `title_negative` — два названия для блоков "Получается отлично" и "Нужно улучшить"
* `penalty` — штраф за нарушение, влияет на расчёт Q-SCORE
* `critical` — флаг критического нарушения (при $\text{score}=0$ ограничивает $\text{Q-SCORE} \le 80$)
* `quote_required` — обязательность цитаты при $\text{score}=0$
* `topic_gate` — для вложений: если `true`, метрика проверяется только при активном блоке депозитов

**Именование полей БД:**
* `general_score` $\to$ `hygiene_score` (расчёт по гигиене)
* `hygiene_results` — массив результатов анализа гигиены
* `deposit_results` — массив результатов анализа депозитов
* `risk_results` — массив результатов анализа рисков

---

## 4. Блок "Список диалогов" (Communications)

### 4.1 Назначение блока
Блок возвращает список последних диалогов менеджера за предыдущий рабочий день. Используется для детального изучения коммуникаций и проверки качества.

### 4.2 Логика выбора даты
API возвращает все доступные в БД диалоги менеджера, которые успели обработаться до конца предыдущего рабочего дня. Отдельный запрос даты не требуется — дата из URL (`date`) используется только для вычисления границы.

**Принцип работы:**
* Сегодня четверг $\implies$ обрезаем всё, что закончилось после среды 18:00 UTC
* При `offset=0` видим последние диалоги (среда)
* При `offset=20` видим следующие 20 диалогов (вторник)
* При `offset=40` — понедельник
* И так далее, пока есть диалоги в БД

| День запроса | Граница данных (cutoff) |
| :--- | :--- |
| Понедельник | Всё до пятницы 18:00 |
| Вторник | Всё до понедельника 18:00 |
| Среда | Всё до вторника 18:00 |
| Четверг | Всё до среды 18:00 |
| Пятница | Всё до четверга 18:00 |
| Суббота | Всё до пятницы 18:00 |
| Воскресенье | Всё до пятницы 18:00 |

### 4.3 Параметры запроса
| Параметр | Тип | Обязательно | Описание |
| :--- | :--- | :--- | :--- |
| `manager_id` | path | Да | ID менеджера (до 8 цифр, дополняется нулями слева) |
| `score` | query | Нет | Фильтр по Q-SCORE: `low` (0–40), `medium` (41–79), `high` (80–100) |
| `client_epk` | query | Нет | Фильтр по ЭПК клиента |
| `offset` | query | Нет | Смещение для пагинации (по умолчанию `0`) |
| `limit` | query | Нет | Количество элементов (по умолчанию `20`, максимум из `COMMUNICATIONS_MAX_LIMIT`) |

### 4.4 Пример запроса
```http
GET /manager/12345/dialogs?score=high&client_epk=12345678901234&offset=0&limit=10
```

### 4.5 Формат ответа (200 OK)
```json
{
  "items": [
    {
      "callId": "550e8400-e29b-41d4-a716-446655440000",
      "type": "call",
      "clientEpk": "12345678901234",
      "occurredAt": "2026-11-04T14:30:00Z",
      "score": 92
    },
    {
      "callId": "660f0509-f39c-51e5-b827-557766550001",
      "type": "call",
      "clientEpk": "98765432109876",
      "occurredAt": "2026-11-04T11:15:00Z",
      "score": 85
    }
  ],
  "hasMore": true
}
```

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `items` | Array[Item] | Массив диалогов (не более `limit` элементов) |
| `hasMore` | bool | Есть ли следующие элементы для загрузки |

**Элемент массива `Item`:**
| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `callId` | string | Уникальный ID диалога |
| `type` | string | Тип коммуникации (всегда `"call"`) |
| `clientEpk` | string | ЭПК клиента |
| `occurredAt` | string | Дата и время совершения звонка (ISO 8601) |
| `score` | int | Итоговый балл Q-SCORE |

### 4.6 Логика пагинации
Пагинация реализована через `OFFSET` + `LIMIT`. Для определения `hasMore` используется оптимизация $\mathcal{O}(1)$:

1. Запрос в БД запрашивает ровно `limit + 1` запись.
2. Если вернулось больше `limit` $\implies$ `hasMore = True` (последняя запись отбрасывается).
3. Если вернулось `limit` или меньше $\implies$ `hasMore = False`.

Такой подход не требует отдельного COUNT-запроса и позволяет скроллить историю диалогов сквозь несколько рабочих дней.

**Пример работы пагинации (сегодня четверг):**
* `offset=0, limit=20` — 15 диалогов за среду (`hasMore=false`)
* `offset=20, limit=20` — 5 диалогов за вторник (`hasMore=false`)
* `offset=40, limit=20` — 10 диалогов за понедельник (`hasMore=false`)

---

### 4.7 Фильтрация по Q-SCORE
Параметр `score` ограничивает выдачу по диапазонам:

| Значение | Диапазон | Описание |
| :--- | :--- | :--- |
| `low` | $0 \le \text{score} \le 40$ | Критически низкий результат |
| `medium` | $41 \le \text{score} \le 79$ | Средний результат |
| `high` | $80 \le \text{score} \le 100$ | Высокий результат |

---

### 4.8 Данные в БД
Диалоги хранятся в `dialog_reports` (JSONB-таблица):

| Поле | Тип | Описание |
| :--- | :--- | :--- |
| `call_id` | Primary Key | ID диалога |
| `manager_id` | `varchar(8)` | ID менеджера |
| `client_epk` | `varchar(128)` | ЭПК клиента |
| `work_date` | `date` | Дата работы (рабочий день) |
| `occurred_at` | `timestamp with tz` | Время диалога |
| `completed_at` | `timestamp with tz` | Время завершения анализа |
| `score` | `float` | Итоговый Q-SCORE |
| `hygiene_results` | `JSONB` | Результаты анализа гигиены |
| `deposit_results` | `JSONB` | Результаты анализа депозитов |
| `risk_results` | `JSONB` | Результаты анализа рисков |
| `hygiene_score` | `float` | Q-SCORE за гигиену |
| `deposit_score` | `float` | Q-SCORE за депозиты |
| `critical_violation` | `boolean` | Флаг критического нарушения |
| `report_payload` | `JSONB` | Полный пейлоад отчёта |

---

### 4.9 Ежедневный процесс
1. **18:00 UTC — `DashboardScheduler.rebuild()`:**
   * Для каждого менеджера:
     * fetch диалогов за `work_date`
     * запустить `PromptAnalysisAgent` $\to$ hygiene + deposit + risk
     * рассчитать Q-SCORE
     * сохранить в `dialog_reports`
2. **Любой момент — API `GET /manager/{id}/dialogs`:**
   * Вычислить предыдущий рабочий день (пропуская сб/вс)
   * Вычислить $\text{cutoff} = \text{prev\_workday 18:00 UTC}$
   * Запросить `limit+1` запись из `dialog_reports`:
     ```sql
     WHERE manager_id = :id
       AND completed_at <= cutoff
       [AND score <= 40]             -- если score=low
       [AND score BETWEEN 41 AND 79] -- если score=medium
       [AND score >= 80]             -- если score=high
       [AND client_epk = :epk]
     ORDER BY completed_at DESC
     LIMIT :limit + 1
     OFFSET :offset
     ```
   * Вернуть `limit` записей + `hasMore`

---

### 4.10 Конфигурация
| Параметр | Тип | Назначение |
| :--- | :--- | :--- |
| `LATEST_COMMUNICATIONS_LIMIT` | `int` | Лимит выдачи по умолчанию (обычно 5) |
| `COMMUNICATIONS_MAX_LIMIT` | `int` | Максимально допустимый лимит запроса |
| `CERTAIN_IMPROVEMENT_COMMUNICATIONS_LIMIT` | `int` | Лимит коммуникаций в Certain Improvement Metric |
| `CERTAIN_IMPROVEMENT_PERIODS_LIMIT` | `int` | Количество завершённых периодов в Certain Improvement Metric |
| `DATA_TTL_DAYS` | `int` | Хранение отчётов в БД (дни) |

---

## 5. Блок "Детальный отчёт по диалогу"

### 5.1 Назначение блока
Возвращает полный отчёт по одному диалогу — результаты анализа, которые были рассчитаны в 18:00.

### 5.2 Эндпоинт
**Метод:** `GET /manager/dialogs/{call_id}`

### 5.3 Параметры
| Параметр | Тип | Обязательно | Описание |
| :--- | :--- | :--- | :--- |
| `call_id` | `path` | Да | Уникальный ID диалога |

### 5.4 Формат ответа (200 OK)
```json
{
  "callId": "550e8400-e29b-41d4-a716-446655440000",
  "clientEpk": "12345678901234",
  "occurredAt": "2026-11-04T14:30:00Z",
  "type": "call",
  "score": 65,
  "deviationsCount": 2,
  "risks": [
    {
      "code": "RISK_01",
      "title": "Клиент планирует уйти из банка",
      "severity": "high"
    }
  ],
  "strengths": "Вы хорошо выполнили следующие критерии: Соблюдение приветствия, Представление, Озвучена цель. Продолжайте придерживаться этого подхода.",
  "improvements": [
    {
      "code": "HYGIENE_03",
      "title": "Не озвучена тема звонка",
      "quote": "Менеджер сразу перешёл к продукту без озвучивания темы",
      "recommendation": "В первые реплики кратко озвучивайте цель звонка."
    }
  ]
}
```

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `callId` | `string` | ID диалога |
| `clientEpk` | `string` | ЭПК клиента |
| `occurredAt` | `datetime` | Время диалога |
| `type` | `string` | Тип коммуникации |
| `score` | `float` | Q-SCORE диалога |
| `deviationsCount` | `int` | Количество нарушений |
| `risks` | `Array[object]` | Список выявленных рисков (`code`, `title`, `severity`) |
| `strengths` | `string` | Сформированный текст по шаблону (1 случайный шаблон + 5 случайных метрик, где $\text{score} = 1$, с `title_positive`) |
| `improvements` | `Array[object]` | Зоны улучшения (список метрик, где $\text{score} = 0$) |

**Элемент массива `risks`:**
| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `code` | `string` | Код риска (например `RISK_01`) |
| `title` | `string` | Название риска |
| `severity` | `string` | Уровень серьёзности: `high`, `medium`, `low`, `critical` |

**Элемент массива `improvements`:**
| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `code` | `string` | Код метрики (например `HYGIENE_03`) |
| `title` | `string` | Название метрики (`title_negative` из criteria YAML) |
| `quote` | `string` | Цитата из диалога (`null` если нет) |
| `recommendation` | `string` | Рекомендация из criteria YAML |

---

### 5.5 Данные в БД
Источник данных — отдельные JSONB-поля таблицы `dialog_reports`:

| Поле | Тип | Описание |
| :--- | :--- | :--- |
| `risk_results` | `JSONB` | Сырые результаты анализа рисков (от LLM) |
| `hygiene_results` | `JSONB` | Сырые результаты анализа гигиены (от LLM) |
| `deposit_results` | `JSONB` | Сырые результаты анализа депозитов (от LLM) |

**Структура элемента `risk_results`:**
| Поле | Тип | Описание |
| :--- | :--- | :--- |
| `code` | `string` | Код риска |
| `title` | `string` | Название риска |
| `score` | `int` | 0 или 1 |
| `severity` | `string` | `high`, `medium`, `low`, `critical` |
| `recommendation` | `string` | Рекомендация |
| `quote` | `string` | Цитата из диалога |

**Структура элемента `hygiene_results` / `deposit_results`:**
| Поле | Тип | Описание |
| :--- | :--- | :--- |
| `code` | `string` | Код метрики |
| `title_positive` | `string` | Название для Strengths |
| `title_negative` | `string` | Название для Improvements |
| `score` | `int` | 0 или 1 |
| `severity` | `string` | Уровень критичности |
| `recommendation` | `string` | Рекомендация |
| `quote` | `string` | Цитата из диалога |

---

### 5.6 Источник данных и трансформация
API-ответ формируется из отдельных JSONB-полей таблицы `dialog_reports`:

1. **18:00 UTC — `DashboardScheduler.rebuild()`:**
   * Fetch диалогов за `work_date`
   * `PromptAnalysisAgent` $\to$ LLM $\to$ hygiene/deposit/risk scores
   * `save_raw_results` $\to$ `dialog_reports`:
     * `hygiene_results = [{code, score, title_positive, title_negative, ...}]`
     * `deposit_results = [{code, score, title_positive, title_negative, ...}]`
     * `risk_results = [{code, score, severity, title, ...}]`
2. **`GET /manager/dialogs/{call_id}`:**
   * Чтение из `dialog_reports WHERE call_id = :id`
   * Трансформация:
     * a. `risks = [code, title, severity]` из `risk_results`
     * b. `strengths` = шаблон + 5 random(`passed, score=1`) из `hygiene_results` + `deposit_results`
     * c. `improvements = [code, title_negative, quote, recommendation]` из `failed (score=0)`
   * Возврат трансформированного пейлоада

---

### 5.7 Пример ответа (полный)
```json
{
  "callId": "550e8400-e29b-41d4-a716-446655440000",
  "clientEpk": "12345678901234",
  "occurredAt": "2026-11-04T14:30:00Z",
  "type": "call",
  "score": 72.5,
  "deviationsCount": 3,
  "risks": [
    {
      "code": "RISK_01",
      "title": "Клиент планирует уйти из банка",
      "severity": "high"
    }
  ],
  "strengths": "Вы хорошо выполнили следующие критерии: Соблюдение приветствия, Представление, Озвучена цель. Продолжайте придерживаться этого подхода.",
  "improvements": [
    {
      "code": "HYGIENE_03",
      "title": "Не озвучена тема звонка",
      "quote": "Менеджер сразу перешёл к продукту без озвучивания темы",
      "recommendation": "В первые реплики кратко озвучивайте цель звонка."
    }
  ]
}
```
