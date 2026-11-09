from datetime import UTC, date, datetime, time, timedelta

from app.agents.prompt_loader import PromptLoader
from app.config import Settings
from app.database.repositories.dashboard_repository import DashboardRepository
from app.database.repositories.dialog_report_repository import DialogReportRepository
from app.schemas.analysis import CriterionResult
from app.schemas.api import DashboardTestDataRequest
from app.schemas.entities import DialogEntity
from app.services.dashboard.client_fio import ClientFioCodec
from app.services.dashboard.dashboard_builder import DashboardBuilder
from app.services.dialog_analysis.dialog_report_builder import build_dialog_report
from app.services.dialog_analysis.scoring import calculate_dialog_score


class DashboardTestDataService:
    def __init__(
        self,
        settings: Settings,
        prompts: PromptLoader,
        reports: DialogReportRepository,
        dashboards: DashboardRepository,
        builder: DashboardBuilder,
    ) -> None:
        self._settings = settings
        self._prompts = prompts
        self._reports = reports
        self._dashboards = dashboards
        self._builder = builder
        self._client_fio = ClientFioCodec(settings)

    async def create(self, request: DashboardTestDataRequest) -> dict:
        self._validate_request(request)
        await self._reports.delete_test_reports(request.manager_ids)
        await self._dashboards.delete_manager_history(request.manager_ids)
        work_dates = self._work_dates(request.date_from, request.date_to)
        reports_count = 0
        manager_ordinals = {}
        for manager_id in request.manager_ids:
            manager_ordinals[manager_id] = 0

        if request.scenario != "no_dialogs":
            for work_date in work_dates:
                for manager_id in request.manager_ids:
                    for sequence in range(request.dialogs_per_workday):
                        values = self._report_values(
                            manager_id,
                            work_date,
                            sequence,
                            manager_ordinals[manager_id],
                            request,
                        )
                        await self._reports.upsert_test_report(values)
                        reports_count += 1
                        manager_ordinals[manager_id] += 1

        for work_date in work_dates:
            await self._builder.rebuild(
                work_date,
                manager_ids=request.manager_ids,
            )

        return {
            "status": "completed",
            "scenario": request.scenario,
            "managers": request.manager_ids,
            "periodStart": str(request.date_from),
            "periodEnd": str(request.date_to),
            "workdays": len(work_dates),
            "dialogsPerWorkday": request.dialogs_per_workday,
            "reportsCreated": reports_count,
            "snapshotsBuilt": len(work_dates) * len(request.manager_ids),
        }

    def _validate_request(self, request: DashboardTestDataRequest) -> None:
        configured = self._settings.static_manager_roles()
        unknown_managers = []
        for manager_id in request.manager_ids:
            if manager_id not in configured:
                unknown_managers.append(manager_id)
        if unknown_managers:
            raise ValueError(
                "Менеджеры отсутствуют в ролевых ENV-списках: "
                f"{unknown_managers}"
            )

        known_codes = set(self._prompts.criteria_by_code)
        unknown_codes = set(request.metric_scores) - known_codes
        if unknown_codes:
            raise ValueError(
                f"Неизвестные коды metric_scores: {sorted(unknown_codes)}"
            )

    @staticmethod
    def _work_dates(date_from: date, date_to: date) -> list[date]:
        result = []
        cursor = date_from
        while cursor <= date_to:
            if cursor.weekday() < 5:
                result.append(cursor)
            cursor += timedelta(days=1)
        return result

    def _report_values(
        self,
        manager_id: str,
        work_date: date,
        sequence: int,
        ordinal: int,
        request: DashboardTestDataRequest,
    ) -> dict:
        marker = work_date.toordinal() + int(manager_id[-1:]) + sequence
        occurred_at = datetime.combine(
            work_date,
            time(hour=10 + sequence % 8, minute=sequence % 60),
            tzinfo=UTC,
        )
        call_id = (
            f"fixture-{request.scenario}-{manager_id}-"
            f"{work_date.isoformat()}-{sequence:03d}"
        )
        client_epk = request.client_epk or f"EPK-{manager_id[-2:]}-{marker % 6 + 1:02d}"
        client_fio = request.client_fio or f"Иванов{marker % 6 + 1} Иван Иванович"
        stored_fio, fio_encrypted = self._client_fio.for_storage(client_fio, False)

        hygiene = self._hygiene_results(request.scenario, marker, ordinal)
        deposit = self._deposit_results(request.scenario, marker)
        risks = self._risk_results(request.scenario, marker)
        self._apply_overrides(hygiene, request.metric_scores)
        self._apply_overrides(deposit, request.metric_scores)
        self._apply_overrides(risks, request.metric_scores)
        self._apply_deposit_gate(deposit)

        score = calculate_dialog_score(
            self._criterion_results(hygiene),
            self._criterion_results(deposit),
            self._prompts.criteria_by_code,
            self._settings.critical_score_cap,
        )
        risks_count = 0
        for item in risks:
            if item["score"] == 0:
                risks_count += 1

        cleaned_text = "Сотрудник: тестовый звонок. Клиент: тестовый ответ."
        source_payload = {
            "channel": "phone",
            "participants": [],
            "utterances": [],
            "source_metadata": {"fixtureScenario": request.scenario},
        }
        dialog = DialogEntity(
            call_id=call_id,
            manager_id=manager_id,
            client_epk=client_epk,
            client_fio=stored_fio,
            client_fio_encrypted=fio_encrypted,
            work_date=work_date,
            occurred_at=occurred_at,
            received_at=occurred_at,
            duration_seconds=60,
            cleaned_text=cleaned_text,
            source_payload=source_payload,
            required_analyzers=["prompt"],
            criteria_version=self._settings.criteria_version,
            prompt_version=self._settings.prompt_version,
            model_name="dashboard-test-fixture",
            created_at=occurred_at,
        )
        report_payload = build_dialog_report(
            dialog,
            final_score=score.final_score,
            deviations_count=score.deviations_count,
            hygiene_results=hygiene,
            deposit_results=deposit,
            risk_results=risks,
            strengths_limit=self._settings.dialog_strengths_limit,
            improvements_limit=self._settings.dialog_improvements_limit,
            positive_templates=self._prompts.positive_templates,
            hidden_metric_codes=self._settings.ui_hidden_metric_codes,
        )

        return {
            "call_id": call_id,
            "manager_id": manager_id,
            "client_epk": client_epk,
            "client_fio": stored_fio,
            "client_fio_encrypted": fio_encrypted,
            "work_date": work_date,
            "occurred_at": occurred_at,
            "cleaned_text": cleaned_text,
            "source_payload": source_payload,
            "hygiene_results": hygiene,
            "deposit_results": deposit,
            "risk_results": risks,
            "audio_results": {},
            "factor_results": {},
            "hygiene_score": score.hygiene_score,
            "deposit_score": score.deposit_score,
            "score": score.final_score,
            "deposit_topic": score.deposit_topic,
            "critical_violation": score.critical_violation,
            "deviations_count": score.deviations_count,
            "risks_count": risks_count,
            "report_payload": report_payload,
            "criteria_version": self._settings.criteria_version,
            "prompt_version": self._settings.prompt_version,
            "model_name": "dashboard-test-fixture",
            "completed_at": occurred_at + timedelta(minutes=5),
            "expires_at": datetime.now(UTC)
            + timedelta(days=self._settings.data_ttl_days),
        }

    def _hygiene_results(
        self,
        scenario: str,
        marker: int,
        ordinal: int,
    ) -> list[dict]:
        results = []
        critical_code = self._first_critical_hygiene_code()
        for index, definition in enumerate(self._prompts.criteria_by_block["hygiene"]):
            score = 1
            if scenario == "mixed":
                score = int((marker + index) % (index + 4) != 0)
            elif scenario == "critical_violation" and definition.code == critical_code:
                score = 0
            elif scenario == "strengths_boundary_80" and definition.code == "HYG_01":
                score = int(ordinal % 5 != 0)
            elif scenario == "improvement_boundary_79" and definition.code == "HYG_01":
                score = int(ordinal % 100 < 79)
            results.append(self._criterion(definition, score, included=True))
        return results

    def _deposit_results(self, scenario: str, marker: int) -> list[dict]:
        topic = scenario != "no_deposit_topic"
        if scenario == "mixed":
            topic = marker % 3 == 0
        results = []
        for index, definition in enumerate(self._prompts.criteria_by_block["deposit"]):
            if definition.code == "DEPOSIT_TOPIC":
                score = int(topic)
            elif scenario == "mixed":
                score = int(topic and (marker + index) % (index + 3) != 0)
            else:
                score = int(topic)
            results.append(
                self._criterion(
                    definition,
                    score,
                    included=topic and definition.code != "DEPOSIT_TOPIC",
                )
            )
        return results

    def _risk_results(self, scenario: str, marker: int) -> list[dict]:
        results = []
        for index, definition in enumerate(self._prompts.criteria_by_block["risk"]):
            score = 1
            if scenario == "mixed":
                score = int(marker % (index + 4) != 0)
            elif scenario == "client_high_risk" and definition.severity == "high":
                score = 0
            elif scenario == "multiple_client_risks" and index < 2:
                score = 0
            results.append(self._criterion(definition, score, included=True))
        return results

    @staticmethod
    def _apply_overrides(items: list[dict], overrides: dict[str, int]) -> None:
        for item in items:
            if item["code"] in overrides:
                item["score"] = overrides[item["code"]]
                item["quote"] = None if item["score"] else "Тестовая цитата нарушения."

    @staticmethod
    def _apply_deposit_gate(items: list[dict]) -> None:
        topic = False
        for item in items:
            if item["code"] == "DEPOSIT_TOPIC":
                topic = item["score"] == 1
                break
        for item in items:
            item["included_in_analytics"] = topic and item["code"] != "DEPOSIT_TOPIC"
            if not topic and item["code"] != "DEPOSIT_TOPIC":
                item["score"] = 0
                item["quote"] = None

    def _first_critical_hygiene_code(self) -> str:
        for definition in self._prompts.criteria_by_block["hygiene"]:
            if definition.severity == "critical":
                return definition.code
        raise ValueError("В каталоге нет критичной Hygiene-метрики")

    @staticmethod
    def _criterion_results(items: list[dict]) -> list[CriterionResult]:
        result = []
        for item in items:
            result.append(
                CriterionResult(
                    code=item["code"],
                    score=item["score"],
                    quote=item["quote"],
                )
            )
        return result

    @staticmethod
    def _criterion(definition, score: int, *, included: bool) -> dict:
        return {
            "code": definition.code,
            "title": definition.title_positive,
            "title_positive": definition.title_positive,
            "title_negative": definition.title_negative,
            "block": definition.block,
            "score": score,
            "quote": None if score else "Тестовая цитата нарушения.",
            "severity": definition.severity,
            "penalty": definition.penalty,
            "quote_required": definition.quote_required,
            "recommendation": definition.recommendation or definition.output_rule,
            "included_in_analytics": included,
        }
