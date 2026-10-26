from types import SimpleNamespace

from app.services.report_orchestrator import ReportOrchestrator


def test_dialog_criterion_statistics() -> None:
    dialogs = [
        SimpleNamespace(
            analysis_results={
                "prompt": {
                    "criteria": [
                        {"code": "A", "score": 1},
                        {"code": "A", "score": 0},
                        {"code": "B", "score": 0},
                    ]
                }
            }
        )
    ]

    result = ReportOrchestrator._aggregate_dialog_criteria(dialogs)

    assert result["A"] == {
        "passed_count": 1,
        "violation_count": 1,
        "communications_count": 2,
    }
    assert result["B"]["violation_count"] == 1


def test_period_criterion_statistics_are_summed() -> None:
    reports = [
        SimpleNamespace(
            details={
                "criteria": {
                    "A": {
                        "passed_count": 3,
                        "violation_count": 1,
                        "communications_count": 4,
                    }
                }
            }
        ),
        SimpleNamespace(
            details={
                "criteria": {
                    "A": {
                        "passed_count": 2,
                        "violation_count": 0,
                        "communications_count": 2,
                    }
                }
            }
        ),
    ]

    assert ReportOrchestrator._merge_period_criteria(reports)["A"] == {
        "passed_count": 5,
        "violation_count": 1,
        "communications_count": 6,
    }
