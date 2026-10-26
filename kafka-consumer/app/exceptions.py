class KafkaConsumerError(Exception):
    """Base exception for expected Kafka Consumer failures."""


class DialogAssemblyError(KafkaConsumerError, ValueError):
    """Stored chunks cannot form one complete contiguous dialog."""


class CleanerRejectedError(KafkaConsumerError):
    """Data Cleaner did not accept a completed dialog."""
