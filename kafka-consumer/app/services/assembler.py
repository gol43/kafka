from app.schemas.dialogs import DialogChunkPayload, StructuredDialog


def assemble_dialog(chunks: list[DialogChunkPayload]) -> StructuredDialog:
    ordered = sorted(chunks, key=lambda chunk: chunk.part)
    if not ordered:
        raise ValueError("Cannot assemble an empty dialog")

    expected_parts = list(range(ordered[-1].part + 1))
    if [chunk.part for chunk in ordered] != expected_parts:
        raise ValueError("Dialog parts are not contiguous from zero")
    if not ordered[-1].is_last or any(chunk.is_last for chunk in ordered[:-1]):
        raise ValueError("Dialog has invalid last-part marker")
    if len({chunk.call_id for chunk in ordered}) != 1:
        raise ValueError("Dialog chunks have different call IDs")
    if len({chunk.manager_id for chunk in ordered}) != 1:
        raise ValueError("Dialog chunks have different manager IDs")

    first = ordered[0]
    utterances = [utterance for chunk in ordered for utterance in chunk.utterances]
    utterances.sort(key=lambda item: (item.start_ms, item.sequence_number))
    text = "\n".join(
        f"{item.speaker_role}: {item.normalized_text or item.text}"
        for item in utterances
    )
    participants = []
    seen = set()
    for chunk in ordered:
        for participant in chunk.participants:
            key = (participant.role, participant.employee_id, participant.phone_number)
            if key not in seen:
                seen.add(key)
                participants.append(participant)

    return StructuredDialog(
        call_id=first.call_id,
        manager_id=first.manager_id,
        occurred_at=first.occurred_at,
        channel=first.channel,
        participants=participants,
        text=text,
        utterances=utterances,
        source_metadata={"parts_count": len(ordered), "last_part": ordered[-1].part},
    )
