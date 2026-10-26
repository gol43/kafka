from prometheus_client import Counter

KAFKA_MESSAGES = Counter(
    "quality_kafka_messages_total", "Consumed Kafka messages", ["outcome"]
)
DIALOG_DISPATCHES = Counter(
    "quality_kafka_dialog_dispatches_total",
    "Dialogs handed to Data Cleaner",
    ["outcome"],
)
