from aiokafka import AIOKafkaProducer

from app.config import Settings
from app.dialog_parser import DialogPart, parse_dialog
from app.schemas import PublishDialogRequest, PublishDialogResponse


class DialogProducerService:
    """Превращает удобный HTTP-диалог в последовательность ProtoBuf-чанков."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_servers,
            max_request_size=settings.kafka_max_message_size,
        )

    async def start(self) -> None:
        await self._producer.start()

    async def close(self) -> None:
        await self._producer.stop()

    async def publish(self, request: PublishDialogRequest) -> PublishDialogResponse:
        parts = parse_dialog(request.dialog_text, request.chunk_max_chars)

        for index, part in enumerate(parts):
            message = self._build_message(
                request=request,
                part=part,
                index=index,
                is_last=index == len(parts) - 1,
            )
            await self._producer.send_and_wait(
                self._settings.kafka_topic,
                value=message.SerializeToString(),
                key=request.call_id.encode("utf-8"),
            )

        return PublishDialogResponse(
            call_id=request.call_id,
            topic=self._settings.kafka_topic,
            chunks_sent=len(parts),
        )

    @staticmethod
    def _build_message(
        *,
        request: PublishDialogRequest,
        part: DialogPart,
        index: int,
        is_last: bool,
    ):
        from app.proto.saluteSpeech_pb2 import RecognitionResponse

        message = RecognitionResponse()
        call = message.call_rec
        call.uuid = request.call_id
        call.call_id = request.call_id
        call.part = index
        call.is_last = is_last
        call.channel = "phone"
        call.info.datetime.FromDatetime(request.occurred_at)

        if request.direction == "outgoing":
            employee = getattr(call, "from")
            client = call.to
            employee_channel = 0
        else:
            employee = call.to
            client = getattr(call, "from")
            employee_channel = 1

        employee.name = request.manager_name
        employee.employee_id = request.manager_id
        client.name = request.client_name
        client.phone_number = request.client_phone

        transcription = message.transcription
        transcription.channel = (
            employee_channel if part.role == "employee" else 1 - employee_channel
        )
        transcription.eou = True
        transcription.eou_reason = 1
        transcription.processed_audio_start.seconds = index * 5
        transcription.processed_audio_end.seconds = index * 5 + 4
        transcription.speaker_info.speaker_id = 1 if part.role == "employee" else 2
        transcription.speaker_info.main_speaker_confidence = 1.0
        transcription.emotions_result.neutral = 1.0

        hypothesis = transcription.results.add()
        hypothesis.text = part.text
        hypothesis.normalized_text = part.text
        hypothesis.end.seconds = 4
        return message
