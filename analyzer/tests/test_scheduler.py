from datetime import date
from types import SimpleNamespace

from app.services.report_promotion import ReportPromotionService


def report(start: date, end: date):
    return SimpleNamespace(period_start=start, period_end=end)


def test_finds_first_consecutive_work_periods_after_a_gap() -> None:
    reports = [
        report(date(2026, 1, 5), date(2026, 1, 9)),
        report(date(2026, 1, 19), date(2026, 1, 23)),
        report(date(2026, 1, 26), date(2026, 1, 30)),
        report(date(2026, 2, 2), date(2026, 2, 6)),
        report(date(2026, 2, 9), date(2026, 2, 13)),
    ]
    selected = ReportPromotionService._first_consecutive(reports, 4)
    assert selected == reports[1:]


def test_no_promotion_when_periods_are_not_consecutive() -> None:
    reports = [
        report(date(2026, 1, 5), date(2026, 1, 9)),
        report(date(2026, 1, 19), date(2026, 1, 23)),
        report(date(2026, 2, 2), date(2026, 2, 6)),
        report(date(2026, 2, 16), date(2026, 2, 20)),
    ]
    assert ReportPromotionService._first_consecutive(reports, 4) == []
