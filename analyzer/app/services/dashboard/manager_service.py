import logging
from datetime import date

from app.database.repositories.dashboard_repository import DashboardRepository
from app.database.repositories.dialog_report_repository import DialogReportRepository
from app.exceptions import EntityNotFoundError

logger = logging.getLogger(__name__)


class ManagerService:
    """Возвращает только готовые snapshot и завершённые dialog reports."""

    def __init__(
        self,
        dashboards: DashboardRepository,
        reports: DialogReportRepository,
    ) -> None:
        self._dashboards = dashboards
        self._reports = reports

    async def dashboard_block(
        self,
        manager_id: str,
        report_date: date,
        name: str,
    ):
        snapshot = await self._snapshot(manager_id, report_date)
        return getattr(snapshot, name)

    async def client_risk(
        self,
        manager_id: str,
        report_date: date,
        client_epk: str,
    ) -> dict:
        snapshot = await self._snapshot(manager_id, report_date)
        payload = snapshot.client_risk_details.get(client_epk)
        if payload is None:
            raise EntityNotFoundError("Риск клиента не найден")
        return payload

    async def improvement(
        self,
        manager_id: str,
        report_date: date,
        metric_code: str,
    ) -> dict:
        snapshot = await self._snapshot(manager_id, report_date)
        payload = snapshot.improvement_details.get(metric_code)
        if payload is None:
            raise EntityNotFoundError("Детализация метрики не найдена")
        return payload

    async def dialogs(
        self,
        *,
        manager_id: str,
        report_date: date,
        limit: int,
        client_epk: str | None,
        date_from: date | None,
        date_to: date | None,
    ) -> list[dict]:
        rows = await self._reports.list_for_manager(
            manager_id=manager_id,
            report_date=report_date,
            limit=limit,
            client_epk=client_epk,
            date_from=date_from,
            date_to=date_to,
        )
        return [
            {
                "callId": row.call_id,
                "type": "call",
                "clientEpk": row.client_epk,
                "occurredAt": row.occurred_at.isoformat(),
                "score": row.score,
            }
            for row in rows
        ]

    async def dialog_report(self, call_id: str) -> dict:
        logger.info("Dialog GET received call_id=%s", call_id)
        report = await self._reports.get(call_id)
        if report is None:
            raise EntityNotFoundError("Отчёт не найден")
        logger.info("Dialog GET returned call_id=%s score=%s", call_id, report.score)
        return report.report_payload

    async def _snapshot(self, manager_id: str, report_date: date):
        logger.info(
            "Dashboard GET manager_id=%s date=%s",
            manager_id,
            report_date,
        )
        snapshot = await self._dashboards.snapshot(manager_id, report_date)
        if snapshot is None:
            raise EntityNotFoundError("Витрина менеджера за дату не сформирована")
        return snapshot
