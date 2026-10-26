"""Generate the approved Prompt 4Q criteria from the business Word document."""
from pathlib import Path
import re
import sys
import json

from docx import Document


def slug_index(row_number: int) -> str:
    return f"GENERAL_{row_number:02d}"


def clean(value: str) -> str:
    return " ".join(value.split())


def main(source: Path, destination: Path) -> None:
    document = Document(source)
    table = document.tables[3]
    destination.mkdir(parents=True, exist_ok=True)
    generated = 0
    for row_number, row in enumerate(table.rows[1:], start=1):
        values = [clean(cell.text) for cell in row.cells]
        marker = values[1].lower()
        title = values[3]
        if "4q" not in marker:
            continue
        if title == "Обещание несоответствующего результата":
            continue
        generated += 1
        code = slug_index(row_number)
        payload = {
            "code": code,
            "title": title,
            "description": values[4],
            "rules": values[5],
            "trigger": values[6],
            "positive_definition": values[7],
            "negative_definition": values[6],
            "good_examples": [values[7]] if values[7] else [],
            "bad_examples": [values[6]] if values[6] else [],
            "output_rule": (
                "Верни score=1, если требование выполнено, и score=0 при нарушении. "
                "Recommendation обязательна всегда. При score=0 включи точную короткую цитату "
                "из диалога и конкретный совет; при score=1 дай краткую положительную рекомендацию."
            ),
            "penalty": int(values[9]),
            "critical": values[10] == "1",
        }
        filename = destination / f"{code.lower()}.yaml"
        # JSON is a strict subset of YAML and keeps generation dependency-free.
        filename.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if generated != 27:
        raise RuntimeError(f"Expected 27 criteria, generated {generated}")
    print(f"Generated {generated} criteria in {destination}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: generate_prompt_criteria.py SOURCE.docx DESTINATION")
    main(Path(sys.argv[1]), Path(sys.argv[2]))

