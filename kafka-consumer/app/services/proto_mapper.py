from datetime import UTC

from google.protobuf.json_format import MessageToDict

from app.schemas.dialogs import (
    DialogChunkPayload,
    EmotionVector,
    Participant,
    Utterance,
    WordAlignment,
)


def _duration_ms(value) -> int:
    return int(value.seconds * 1000 + value.nanos / 1_000_000)


def _normalize_manager_id(value: str) -> str:
    if not value or not value.isdigit() or len(value) > 8:
        raise ValueError("Invalid manager employee_id")
    return value.zfill(8)


def _resolve_speaker_role(employee_is_to: bool, channel: int) -> str:
    """Channel zero belongs to the caller; channel one belongs to the callee."""
    employee_is_caller = not employee_is_to
    return "employee" if (channel == 0) == employee_is_caller else "client"


def map_response(message) -> DialogChunkPayload | None:
    if message.WhichOneof("record") != "call_rec":
        return None
    call = message.call_rec
    if message.WhichOneof("response") != "transcription":
        return None

    from_participant = getattr(call, "from")
    from_employee_id = from_participant.employee_id.strip()
    to_employee_id = call.to.employee_id.strip()
    if not from_employee_id and not to_employee_id:
        raise ValueError("Call has no manager employee_id")
    employee_is_to = not from_employee_id
    employee = call.to if employee_is_to else from_participant
    manager_id = _normalize_manager_id(employee.employee_id)
    participants = [
        Participant(
            role="employee" if employee_is_to else "client",
            name=call.to.name or None,
            phone_number=call.to.phone_number or None,
            employee_id=call.to.employee_id or None,
        ),
        Participant(
            role="client" if employee_is_to else "employee",
            name=from_participant.name or None,
            phone_number=from_participant.phone_number or None,
            employee_id=from_participant.employee_id or None,
        ),
    ]
    transcription = message.transcription
    results = list(transcription.results)
    if not results:
        return None
    hypothesis = results[0]
    start_ms = _duration_ms(transcription.processed_audio_start) + _duration_ms(
        hypothesis.start
    )
    end_ms = _duration_ms(transcription.processed_audio_start) + _duration_ms(
        hypothesis.end
    )
    role = _resolve_speaker_role(employee_is_to, transcription.channel)
    emotions = transcription.emotions_result
    utterance = Utterance(
        sequence_number=int(call.part),
        speaker_role=role,
        speaker_id=transcription.speaker_info.speaker_id,
        channel=transcription.channel,
        text=hypothesis.text,
        normalized_text=hypothesis.normalized_text or hypothesis.text,
        start_ms=start_ms,
        end_ms=end_ms,
        eou=transcription.eou,
        eou_reason=str(transcription.eou_reason),
        main_speaker_confidence=transcription.speaker_info.main_speaker_confidence,
        emotions=EmotionVector(
            **MessageToDict(emotions, preserving_proto_field_name=True)
        ),
        word_alignments=[
            WordAlignment(
                word=item.word,
                start_ms=_duration_ms(item.start),
                end_ms=_duration_ms(item.end),
            )
            for item in hypothesis.word_alignments
        ],
    )
    occurred_at = None
    if call.info.datetime.seconds or call.info.datetime.nanos:
        occurred_at = call.info.datetime.ToDatetime(tzinfo=UTC)
    return DialogChunkPayload(
        call_id=call.uuid,
        part=call.part,
        is_last=call.is_last,
        occurred_at=occurred_at,
        channel=call.channel or None,
        manager_id=manager_id,
        participants=participants,
        utterances=[utterance],
    )
