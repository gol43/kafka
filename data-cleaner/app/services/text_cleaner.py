import re
from pathlib import Path

import yaml


class TextCleaner:
    def __init__(self, dictionary_path: Path):
        data = yaml.safe_load(dictionary_path.read_text(encoding="utf-8")) or {}
        roots = [re.escape(item) for values in data.values() for item in values]
        self._roots = (
            re.compile(r"\b(?:" + "|".join(roots) + r")\w*\b", re.IGNORECASE)
            if roots
            else None
        )
        self._email = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-zА-Яа-я]{2,}\b")
        self._digits = re.compile(r"\d")

    def clean(self, value: str) -> str:
        result = self._email.sub("DATA", value)
        if self._roots is not None:
            result = self._roots.sub("DATA", result)
        return self._digits.sub("#", result)
