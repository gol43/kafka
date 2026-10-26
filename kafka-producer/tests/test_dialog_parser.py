from app.dialog_parser import parse_dialog


def test_parses_roles_and_splits_long_utterance() -> None:
    parts = parse_dialog(
        "Сотрудник: Добрый день, я ваш персональный менеджер\n"
        "Клиент: Расскажите про вклад",
        chunk_max_chars=20,
    )

    assert [part.role for part in parts] == [
        "employee",
        "employee",
        "employee",
        "client",
    ]
    assert all(len(part.text) <= 20 for part in parts)


def test_unmarked_lines_alternate_roles() -> None:
    parts = parse_dialog("Здравствуйте\nДобрый день", chunk_max_chars=100)
    assert [part.role for part in parts] == ["employee", "client"]
