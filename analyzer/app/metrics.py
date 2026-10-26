from prometheus_client import Counter, Gauge

ANALYZER_CALLBACKS = Counter(
    "quality_analyzer_callbacks_total", "Cleaner callbacks", ["outcome"]
)
ANALYZER_JOBS = Counter(
    "quality_analyzer_jobs_total", "Finished analyzer jobs", ["job_type", "outcome"]
)
GIGACHAT_REQUESTS = Counter(
    "quality_gigachat_requests_total",
    "GigaChat HTTP requests",
    ["operation", "outcome"],
)
GIGACHAT_ACTIVE = Gauge(
    "quality_gigachat_active_requests", "Active GigaChat HTTP requests"
)
