import base64

import orjson
import pytest

from app.schemas.dialogs import CleanerRequest, StructuredDialog


def test_manager_id_is_normalized() -> None:
    dialog = StructuredDialog(
        call_id="call",
        manager_id="42",
        participants=[],
        text="непустой диалог",
        utterances=[],
    )
    assert dialog.manager_id == "00000042"


def test_empty_dialog_is_rejected() -> None:
    with pytest.raises(ValueError):
        StructuredDialog(
            call_id="call", manager_id="42", participants=[], text="   ", utterances=[]
        )


def test_cleaner_request_decodes_strict_base64() -> None:
    raw = orjson.dumps({"call_id": "call"})
    request = CleanerRequest(
        call_id="call", encrypted=False, payload=base64.b64encode(raw).decode()
    )
    assert request.decoded_payload() == raw
