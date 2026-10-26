from prometheus_client import Counter

CLEANER_ACCEPTED = Counter("quality_cleaner_accepted_total", "Accepted cleaner jobs")
CLEANER_PROCESSED = Counter(
    "quality_cleaner_processed_total", "Processed cleaner jobs", ["outcome"]
)
CLEANER_CALLBACKS = Counter(
    "quality_cleaner_callbacks_total", "Cleaner callbacks", ["outcome"]
)
