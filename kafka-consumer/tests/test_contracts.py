import pytest

from app.schemas.dialogs import DialogChunkPayload


def test_manager_id_is_zero_padded() -> None:
    payload = DialogChunkPayload(
        call_id="call",
        part=0,
        is_last=False,
        manager_id="123",
        participants=[],
        utterances=[],
    )
    assert payload.manager_id == "00000123"


def test_manager_id_over_eight_digits_is_rejected() -> None:
    with pytest.raises(ValueError):
        DialogChunkPayload(
            call_id="call",
            part=0,
            is_last=False,
            manager_id="123456789",
            participants=[],
            utterances=[],
        )
