from app.proto.saluteSpeech_pb2 import RecognitionResponse

from app.services.proto_mapper import _resolve_speaker_role, map_response


def test_outgoing_call_channels() -> None:
    assert _resolve_speaker_role(employee_is_to=False, channel=0) == "employee"
    assert _resolve_speaker_role(employee_is_to=False, channel=1) == "client"


def test_incoming_call_channels() -> None:
    assert _resolve_speaker_role(employee_is_to=True, channel=0) == "client"
    assert _resolve_speaker_role(employee_is_to=True, channel=1) == "employee"


def test_mapper_preserves_emotions_timestamps_and_normalized_manager() -> None:
    message = RecognitionResponse()
    message.call_rec.uuid = "call-1"
    message.call_rec.part = 2
    message.call_rec.is_last = True
    getattr(message.call_rec, "from").name = "Менеджер"
    getattr(message.call_rec, "from").employee_id = "42"
    message.call_rec.to.phone_number = "+79990000000"
    message.call_rec.info.datetime.seconds = 1_700_000_000
    message.transcription.channel = 0
    message.transcription.eou = True
    message.transcription.processed_audio_start.seconds = 3
    message.transcription.emotions_result.positive = 0.75
    message.transcription.speaker_info.speaker_id = 7
    message.transcription.speaker_info.main_speaker_confidence = 0.9
    hypothesis = message.transcription.results.add()
    hypothesis.text = "сорок два"
    hypothesis.normalized_text = "42"
    hypothesis.start.seconds = 1
    hypothesis.end.seconds = 2

    chunk = map_response(message)

    assert chunk is not None
    assert chunk.call_id == "call-1"
    assert chunk.manager_id == "00000042"
    assert chunk.utterances[0].speaker_role == "employee"
    assert chunk.utterances[0].start_ms == 4000
    assert chunk.utterances[0].end_ms == 5000
    assert chunk.utterances[0].emotions.positive == 0.75
    assert chunk.utterances[0].speaker_id == 7
