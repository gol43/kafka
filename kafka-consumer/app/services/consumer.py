import logging

from aiokafka import AIOKafkaConsumer

from app.config import Settings
from app.metrics import KAFKA_MESSAGES
from app.services.chunk_service import ChunkService
from app.services.proto_mapper import map_response

logger = logging.getLogger(__name__)


class DialogConsumer:
    def __init__(self, settings: Settings, chunks: ChunkService):
        self._settings = settings
        self._chunks = chunks
        self._consumer = AIOKafkaConsumer(
            settings.kafka_topic,
            bootstrap_servers=settings.kafka_servers,
            group_id=settings.kafka_group_id,
            enable_auto_commit=False,
            fetch_max_bytes=settings.kafka_max_message_size,
            max_partition_fetch_bytes=settings.kafka_max_message_size,
        )
        self._running = False

    async def run(self) -> None:
        from app.proto.saluteSpeech_pb2 import RecognitionResponse

        await self._consumer.start()
        self._running = True
        try:
            async for record in self._consumer:
                try:
                    message = RecognitionResponse.FromString(record.value)
                    chunk = map_response(message)
                    if chunk is not None:
                        await self._chunks.handle(chunk)
                        KAFKA_MESSAGES.labels(outcome="processed").inc()
                    else:
                        KAFKA_MESSAGES.labels(outcome="ignored").inc()
                except Exception:
                    KAFKA_MESSAGES.labels(outcome="dropped").inc()
                    logger.exception(
                        "Kafka message was dropped", extra={"offset": record.offset}
                    )
                finally:
                    await self._consumer.commit()
                if not self._running:
                    break
        finally:
            await self._consumer.stop()

    async def stop(self) -> None:
        self._running = False

    @property
    def running(self) -> bool:
        return self._running
