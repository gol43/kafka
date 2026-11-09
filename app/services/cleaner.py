import re
from pathlib import Path

import yaml


class TextCleaner:
    """Детерминированная очистка текста; словарь загружается один раз."""

    LABELS = {
        "names": "[DATA_NAME]",
        "surnames": "[DATA_SURNAME]",
        "patronymics": "[DATA_PATRONYMIC]",
        "locations": "[DATA_LOCATION]",
        "streets": "[DATA_STREET]",
        "organizations": "[DATA_ORGANIZATION]",
        "legal_forms": "[DATA_LEGAL_FORM]",
        "special": "[DATA_SPECIAL]",
    }
    TOKEN = re.compile(r"[А-Яа-яЁёA-Za-z]+(?:[-‑][А-Яа-яЁёA-Za-z]+)*|\d+|\s+|.", re.DOTALL)
    PHONE = re.compile(r"(?<!\w)(?:\+7|8)[\s(.-]*\d{3}[\s).-]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}(?!\w)")
    CARD = re.compile(r"(?<!\d)(?:\d{4}[\s-]?){3}\d{4}(?!\d)")
    EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
    SNILS = re.compile(r"(?<!\d)\d{3}[- ]?\d{3}[- ]?\d{3}[- ]?\d{2}(?!\d)")
    MONTHS = frozenset("января февраля марта апреля мая июня июля августа сентября октября ноября декабря".split())
    DATE = re.compile(r"(?<!\w)(?:[1-9]|[12]\d|3[01])(?:-?(?:го|е|ое))?\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\b", re.IGNORECASE)

    def __init__(self, dictionary_path: Path | None = None):
        path = dictionary_path or Path(__file__).resolve().parent.parent / "utils" / "elements.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        self.lookup: dict[str, str] = {}
        self.max_words = 1
        self.exceptions = {self._key(word) for word in raw.get("exceptions", [])}
        for category, label in self.LABELS.items():
            for value in raw.get(category, []):
                key = self._key(str(value))
                if key and key not in self.exceptions:
                    self.lookup[key] = label
                    self.max_words = max(self.max_words, len(key.split()))

    @staticmethod
    def _key(value: str) -> str:
        return " ".join(value.casefold().replace("ё", "е").replace("‑", "-").split())

    def clean(self, text: str) -> str:
        if not text:
            return text
        protected: list[str] = []

        def protect(match: re.Match, label: str) -> str:
            protected.append(label)
            return chr(0xE000 + len(protected) - 1)

        for pattern, label in ((self.EMAIL, "[DATA_EMAIL]"), (self.PHONE, "[DATA_PHONE]"),
                               (self.CARD, "[DATA_CARD]"), (self.SNILS, "[DATA_SNILS]")):
            text = pattern.sub(lambda match, tag=label: protect(match, tag), text)
        text = self.DATE.sub(lambda match: protect(match, match.group()), text)

        tokens = self.TOKEN.findall(text)
        output = []
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if not token[0].isalpha():
                output.append("#" * len(token) if token.isdigit() else token)
                index += 1
                continue
            end = index + 1
            words = [token]
            candidates = [(self._key(token), end)]
            while len(words) < self.max_words and end + 1 < len(tokens):
                if not tokens[end].isspace() or not tokens[end + 1][0].isalpha():
                    break
                words.append(tokens[end + 1])
                end += 2
                candidates.append((self._key(" ".join(words)), end))
            matched = None
            for key, candidate_end in reversed(candidates):
                if key in self.exceptions:
                    matched = ("".join(tokens[index:candidate_end]), candidate_end)
                    break
                label = self.lookup.get(key)
                if label:
                    matched = (label, candidate_end)
                    break
            if matched:
                output.append(matched[0])
                index = matched[1]
            else:
                output.append(token)
                index += 1
        result = "".join(output)
        for position, value in enumerate(protected):
            result = result.replace(chr(0xE000 + position), value)
        return result
