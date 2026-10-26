from pathlib import Path

from app.services.text_cleaner import TextCleaner


def test_cleaner_masks_roots_digits_and_email(tmp_path: Path) -> None:
    dictionary = tmp_path / "roots.yaml"
    dictionary.write_text("names:\n  - иван\n", encoding="utf-8")
    cleaner = TextCleaner(dictionary)
    result = cleaner.clean("Иванов, телефон 123, test@example.com")
    assert "Иван" not in result
    assert "123" not in result
    assert "test@example.com" not in result


def test_cleaner_preserves_non_pii_text(tmp_path: Path) -> None:
    dictionary = tmp_path / "roots.yaml"
    dictionary.write_text("cities:\n  - москва\n", encoding="utf-8")
    cleaner = TextCleaner(dictionary)
    assert (
        cleaner.clean("Пишите TEST@example.com, офис Москва")
        == "Пишите DATA, офис DATA"
    )
