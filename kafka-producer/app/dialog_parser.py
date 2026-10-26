import re
from dataclasses import dataclass
from typing import Literal

SpeakerRole = Literal["employee", "client"]

ROLE_PATTERN = re.compile(
    r"^\s*(сотрудник|менеджер|employee|manager|клиент|client)\s*:\s*(.+?)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class DialogPart:
    role: SpeakerRole
    text: str


def parse_dialog(dialog_text: str, chunk_max_chars: int) -> list[DialogPart]:
    """Разбирает реплики и делит только длинные реплики по границам слов."""

    utterances: list[DialogPart] = []
    fallback_role: SpeakerRole = "employee"

    for raw_line in filter(None, (line.strip() for line in dialog_text.splitlines())):
        match = ROLE_PATTERN.match(raw_line)
        if match:
            marker, text = match.groups()
            role: SpeakerRole = (
                "client" if marker.lower() in {"клиент", "client"} else "employee"
            )
        else:
            role = fallback_role
            text = raw_line

        for fragment in _split_by_words(text, chunk_max_chars):
            utterances.append(DialogPart(role=role, text=fragment))
        fallback_role = "client" if role == "employee" else "employee"

    if not utterances:
        raise ValueError("Диалог не содержит ни одной непустой реплики")
    return utterances


def _split_by_words(value: str, limit: int) -> list[str]:
    words = value.split()
    result: list[str] = []
    current: list[str] = []

    for word in words:
        candidate = " ".join([*current, word])
        if current and len(candidate) > limit:
            result.append(" ".join(current))
            current = [word]
        else:
            current.append(word)

    if current:
        result.append(" ".join(current))
    return result
