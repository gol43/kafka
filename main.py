import asyncio
import logging
from contextlib import suppress

from aiokafka import AIOKafkaConsumer
from pydantic import ValidationError

from app.config import Settings
from app.infrastructure.prometheus.metrics import (
    KAFKA_MESSAGES_FAILED,
    KAFKA_MESSAGES_RECEIVED,
)
from app.services.kafka.kafka_dialog_service import KafkaDialogService


logger = logging.getLogger(__name__)


class KafkaDialogConsumer:

    WORKERS_COUNT = 10
    QUEUE_MAX_SIZE = 1000

    def __init__(
        self,
        settings: Settings,
        service: KafkaDialogService,
    ):
        self.settings = settings
        self.service = service

        self.consumer: AIOKafkaConsumer | None = None

        # Основная task, которая читает Kafka
        self.task: asyncio.Task | None = None

        self.stopped = asyncio.Event()

        # Ограниченная очередь.
        # Больше 1000 сообщений в память не забираем.
        self.queue: asyncio.Queue = asyncio.Queue(
            maxsize=self.QUEUE_MAX_SIZE
        )

        # Постоянные workers.
        self.workers: list[asyncio.Task] = []

    async def start(self) -> None:
        logger.info("Starting Kafka consumer")

        topics = self.settings.kafka_topics_list

        logger.info("Kafka topics: %s", topics)

        if not topics:
            logger.info("No topics to consume from")
            return

        self.consumer = AIOKafkaConsumer(
            *topics,
            bootstrap_servers=(
                self.settings.kafka_sber_user_bootstrap_servers
            ),
            group_id=self.settings.kafka_sber_user_group_id,
            client_id=self.settings.app_name,
            auto_offset_reset="earliest",
            enable_auto_commit=False,
            max_poll_interval_ms=600000,
            max_poll_records=100,
            session_timeout_ms=30000,
            heartbeat_interval_ms=5000,
        )

        await self.consumer.start()

        # Создаём фиксированное количество workers.
        self.workers = [
            asyncio.create_task(
                self._worker(worker_id),
                name=f"KafkaDialogWorker-{worker_id}",
            )
            for worker_id in range(self.WORKERS_COUNT)
        ]

        # Отдельная task только читает Kafka.
        self.task = asyncio.create_task(
            self._run(),
            name="KafkaDialogConsumer",
        )

        logger.info(
            "Started KafkaDialogConsumer "
            "for topics=%s workers=%d queue_size=%d",
            topics,
            self.WORKERS_COUNT,
            self.QUEUE_MAX_SIZE,
        )

    async def stop(self) -> None:
        logger.info("Stopping Kafka consumer")

        self.stopped.set()

        # Перестаём читать новые сообщения из Kafka.
        if self.task is not None:
            self.task.cancel()

            with suppress(asyncio.CancelledError):
                await self.task

            self.task = None

        # Ждём обработки сообщений,
        # которые уже находятся в очереди.
        await self.queue.join()

        # После опустошения очереди останавливаем workers.
        for worker in self.workers:
            worker.cancel()

        for worker in self.workers:
            with suppress(asyncio.CancelledError):
                await worker

        self.workers.clear()

        if self.consumer is not None:
            await self.consumer.stop()
            self.consumer = None

        logger.info("Kafka consumer stopped")

    async def _run(self) -> None:
        """
        Эта coroutine только читает сообщения из Kafka
        и складывает их в ограниченную очередь.

        Бизнес-логика здесь больше не выполняется.
        """

        assert self.consumer is not None

        try:
            async for message in self.consumer:

                # Если очередь заполнена до 1000 сообщений,
                # await остановится здесь, пока worker
                # не освободит место.
                await self.queue.put(message)

                if self.stopped.is_set():
                    break

        except asyncio.CancelledError:
            raise

        except Exception as e:
            logger.error(
                "Error in KafkaDialogConsumer: %s",
                e,
                exc_info=True,
            )
            raise

    async def _worker(self, worker_id: int) -> None:
        """
        Постоянный worker.

        Всего одновременно существует WORKERS_COUNT workers.
        Новая asyncio.Task на каждое Kafka-сообщение
        НЕ создаётся.
        """

        logger.info(
            "Kafka worker %d started",
            worker_id,
        )

        while True:
            try:
                # Ждём сообщение из внутренней очереди.
                message = await self.queue.get()

                try:
                    await self._handle_message(message)

                except asyncio.CancelledError:
                    raise

                except Exception as e:
                    logger.error(
                        "Kafka worker %d failed: %s",
                        worker_id,
                        e,
                        exc_info=True,
                    )

                finally:
                    # Сообщаем asyncio.Queue,
                    # что элемент обработан.
                    self.queue.task_done()

            except asyncio.CancelledError:
                logger.info(
                    "Kafka worker %d stopped",
                    worker_id,
                )
                raise

    async def _handle_message(self, message) -> None:
        """
        Старая логика обработки сообщения.
        """

        assert self.consumer is not None

        logger.info(
            "Kafka message received: "
            "topic=%s, partition=%d, offset=%d",
            message.topic,
            message.partition,
            message.offset,
        )

        KAFKA_MESSAGES_RECEIVED.inc()

        try:
            await self.service.process_payload(
                message.value
            )

        except (ValueError, ValidationError) as e:
            KAFKA_MESSAGES_FAILED.inc()

            logger.error(
                "Kafka message processing failed: %s",
                e,
            )

            await self.consumer.commit()

        except Exception as e:
            KAFKA_MESSAGES_FAILED.inc()

            logger.error(
                "Unexpected error processing Kafka message: "
                "topic=%s, partition=%d, offset=%d, error=%s",
                message.topic,
                message.partition,
                message.offset,
                e,
            )

            await self.consumer.commit()