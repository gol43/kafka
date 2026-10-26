# Нагрузочная проверка

Сценарий `k6-smoke.js` одновременно проверяет readiness обоих HTTP-сервисов и два completed-only GET пути Analyzer. Ожидаемый `404` для отсутствующего отчёта считается успешным ответом бизнес-контракта.

Локальный запуск после `docker compose up -d postgres data-cleaner analyzer`:

```bash
docker run --rm \
  -e VUS=20 \
  -e DURATION=10s \
  -e INTERNAL_API_TOKEN=local-development-token \
  -v "$PWD/load-tests:/scripts" \
  grafana/k6 run /scripts/k6-smoke.js
```

Порог smoke-проверки: меньше 1% транспортных ошибок, `p95 < 250 ms`, `p99 < 500 ms`. Для стенда длительность и число VU задаются через `DURATION` и `VUS` без изменения сценария.
