from prometheus_client import Counter, Gauge

ANALYZER_CALLBACKS = Counter(
    "analyzer_callbacks_total",
    "Dialog callbacks received by outcome",
    ["outcome"],
)
ANALYZER_JOBS = Counter(
    "analyzer_jobs_total",
    "Dialog analysis jobs by outcome",
    ["job_type", "outcome"],
)
GIGACHAT_ACTIVE = Gauge(
    "gigachat_active_requests",
    "GigaChat requests currently holding the shared semaphore",
)
GIGACHAT_REQUESTS = Counter(
    "gigachat_requests_total",
    "GigaChat requests by outcome",
    ["outcome"],
)
