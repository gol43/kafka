from datetime import UTC, date, datetime, time, timedelta

from app.agents.prompt_loader import PromptLoader
from app.config import Settings
from app.database.repositories.dialog_report_repository import DialogReportRepository
from app.schemas.analysis import CriterionResult
from app.services.dashboard.dashboard_builder import DashboardBuilder
from app.services.dialog_analysis.scoring import calculate_dialog_score


class DashboardTestDataService:
    """Создаёт воспроизводимую историю, затем запускает production builder."""

    MANAGERS = ("00000001", "00000002")

    def __init__(
        self,
        settings: Settings,
        prompts: PromptLoader,
        reports: DialogReportRepository,
        builder: DashboardBuilder,
    ) -> None:
        self._settings = settings
        self._prompts = prompts
        self._reports = reports
        self._builder = builder

    async def create(self, end_date: date, days: int) -> dict:
        start_date = end_date - timedelta(days=days - 1)
        work_dates = [
            start_date + timedelta(days=offset)
            for offset in range(days)
            if (start_date + timedelta(days=offset)).weekday() < 5
        ]

        reports_count = 0
        for work_date in work_dates:
            for manager_id in self.MANAGERS:
                await self._reports.upsert_test_report(
                    self._report_values(manager_id, work_date)
                )
                reports_count += 1

        # Тот же builder и тот же порядок дат, что использовались бы production.
        for work_date in work_dates:
            await self._builder.rebuild(work_date)

        return {
            "status": "completed",
            "managers": list(self.MANAGERS),
            "periodStart": str(work_dates[0]) if work_dates else str(start_date),
            "periodEnd": str(work_dates[-1]) if work_dates else str(end_date),
            "reportsCreated": reports_count,
            "snapshotsBuilt": len(work_dates) * len(self.MANAGERS),
        }

    def _report_values(self, manager_id: str, work_date: date) -> dict:
        marker = work_date.toordinal() + int(manager_id[-1])
        occurred_at = datetime.combine(work_date, time(hour=12), tzinfo=UTC)
        call_id = f"fixture-{manager_id}-{work_date.isoformat()}"
        client_epk = f"EPK-{manager_id[-2:]}-{marker % 6 + 1:02d}"

        hygiene = self._block_results("general", marker)
        deposit_topic = marker % 3 == 0
        deposit = self._deposit_results(marker, deposit_topic)
        risks = self._risk_results(marker)

        score = calculate_dialog_score(
            [CriterionResult(code=item["code"], score=item["score"], quote=item["quote"]) for item in hygiene],
            [CriterionResult(code=item["code"], score=item["score"], quote=item["quote"]) for item in deposit],
            self._prompts.criteria_by_code,
            self._settings.critical_score_cap,
        )
        detected_risks = [item for item in risks if item["score"] == 0]
        failed = [
            item
            for item in hygiene + deposit
            if item["included_in_analytics"] and item["score"] == 0
        ]
        passed = [
            item
            for item in hygiene + deposit
            if item["included_in_analytics"] and item["score"] == 1
        ]

        return {
            "call_id": call_id,
            "manager_id": manager_id,
            "client_epk": client_epk,
            "work_date": work_date,
            "occurred_at": occurred_at,
            "cleaned_text": "Сотрудник: тестовый звонок. Клиент: тестовый ответ.",
            "hygiene_results": hygiene,
            "deposit_results": deposit,
            "risk_results": risks,
            "audio_results": {},
            "factor_results": {},
            "general_score": score.general_score,
            "deposit_score": score.deposit_score,
            "score": score.final_score,
            "deposit_topic": score.deposit_topic,
            "critical_violation": score.critical_violation,
            "deviations_count": score.deviations_count,
            "risks_count": len(detected_risks),
            "report_payload": {
                "callId": call_id,
                "clientEpk": client_epk,
                "occurredAt": occurred_at.isoformat(),
                "type": "call",
                "score": score.final_score,
                "deviationsCount": score.deviations_count,
                "risk": detected_risks[0] if detected_risks else None,
                "strengths": {
                    "text": "Тестовые сильные стороны коммуникации.",
                    "metrics": passed[:3],
                },
                "improvements": failed[:3],
            },
            "criteria_version": self._settings.criteria_version,
            "prompt_version": self._settings.prompt_version,
            "model_name": "dashboard-test-fixture",
            "completed_at": occurred_at + timedelta(minutes=5),
            "expires_at": datetime.now(UTC)
            + timedelta(days=self._settings.data_ttl_days),
        }

    def _block_results(self, block: str, marker: int) -> list[dict]:
        results = []
        for index, definition in enumerate(self._prompts.criteria_by_block[block]):
            score = int((marker + index) % (index + 4) != 0)
            results.append(
                self._criterion(definition, score, included=True)
            )
        return results

    def _deposit_results(self, marker: int, topic: bool) -> list[dict]:
        results = []
        for index, definition in enumerate(self._prompts.criteria_by_block["deposit"]):
            if definition.topic_gate:
                score = int(topic)
            else:
                score = int(topic and (marker + index) % (index + 3) != 0)
            results.append(
                self._criterion(
                    definition,
                    score,
                    included=topic and not definition.topic_gate,
                )
            )
        return results

    def _risk_results(self, marker: int) -> list[dict]:
        results = []
        for index, definition in enumerate(self._prompts.criteria_by_block["risk"]):
            detected = marker % (index + 4) == 0
            results.append(
                self._criterion(definition, int(not detected), included=True)
            )
        return results

    @staticmethod
    def _criterion(definition, score: int, *, included: bool) -> dict:
        return {
            "code": definition.code,
            "title": definition.title,
            "block": definition.block,
            "score": score,
            "quote": None if score else "Тестовая цитата нарушения.",
            "severity": definition.severity,
            "penalty": definition.penalty,
            "critical": definition.critical,
            "quote_required": definition.quote_required,
            "recommendation": definition.recommendation or definition.output_rule,
            "included_in_analytics": included,
        }
