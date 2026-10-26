from datetime import UTC, datetime

from app.services.calendar_policy import resolve_work_date


def dt(day: int, hour: int) -> datetime:
    return datetime(2026, 10, day, hour, tzinfo=UTC)


def test_friday_after_cutoff_is_dropped() -> None:
    assert resolve_work_date(dt(23, 18)) is None


def test_sunday_after_cutoff_moves_to_monday() -> None:
    assert str(resolve_work_date(dt(25, 18))) == "2026-10-26"


def test_monday_after_cutoff_moves_to_tuesday() -> None:
    assert str(resolve_work_date(dt(19, 18))) == "2026-10-20"
