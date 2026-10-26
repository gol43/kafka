import pytest

from app.schemas.dialogs import DialogChunkPayload
from app.services.assembler import assemble_dialog


def chunk(part: int, is_last: bool) -> DialogChunkPayload:
    return DialogChunkPayload(
        call_id="call",
        part=part,
        is_last=is_last,
        manager_id="42",
        participants=[],
        utterances=[],
    )


def test_out_of_order_parts_are_sorted_and_assembled() -> None:
    dialog = assemble_dialog([chunk(1, True), chunk(0, False)])
    assert dialog.source_metadata == {"parts_count": 2, "last_part": 1}


def test_missing_part_is_rejected() -> None:
    with pytest.raises(ValueError, match="not contiguous"):
        assemble_dialog([chunk(0, False), chunk(2, True)])


def test_last_marker_must_be_on_highest_part() -> None:
    with pytest.raises(ValueError, match="last-part"):
        assemble_dialog([chunk(0, True), chunk(1, False)])
