import logging
from datetime import date

from app.database.repositories.dashboard_repository import DashboardRepository
from app.database.repositories.dialog_report_repository import DialogReportRepository
from app.config import Settings
from app.exceptions import EntityNotFoundError
from app.services.dashboard.client_fio import ClientFioCodec

logger = logging.getLogger(__name__)


class ManagerService:
    """Возвращает только готовые snapshot и завершённые dialog reports."""

    def __init__(
        self,
        dashboards: DashboardRepository,
        reports: DialogReportRepository,
        settings: Settings,
    ) -> None:
        self._dashboards = dashboards
        self._reports = reports
        self._client_fio = ClientFioCodec(settings)

    async def dashboard_block(
        self,
        manager_id: str,
        name: str,
    ):
        _, payload = await self._latest_value(manager_id, name)
        return self._public(payload)

    async def certain_client_risk(
        self,
        manager_id: str,
        client_epk: str,
    ) -> dict:
        _, client_risks = await self._latest_value(
            manager_id,
            "certain_client_risks",
        )
        payload = client_risks.get(client_epk)
        if payload is None:
            raise EntityNotFoundError("Риск клиента не найден")
        return self._public(payload)

    async def certain_improvement_metric(
        self,
        manager_id: str,
        metric_code: str,
    ) -> dict:
        _, metric_details = await self._latest_value(
            manager_id,
            "certain_improvement_metrics",
        )
        payload = metric_details.get(metric_code)
        if payload is None:
            raise EntityNotFoundError("Детализация метрики не найдена")
        return self._public(payload)

    async def dialogs(
        self,
        *,
        manager_id: str,
        score: str | None = None,
        client_epk: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        offset: int = 0,
        limit: int = 5,
    ) -> dict:
        report_date = await self._dashboards.latest_report_date(manager_id)
        if report_date is None:
            raise EntityNotFoundError("Витрина менеджера не сформирована")

        rows = await self._reports.list_completed_dialogs(
            manager_id=manager_id,
            work_date=report_date,
            score=score,
            client_epk=client_epk,
            date_from=date_from,
            date_to=date_to,
            offset=offset,
            limit=limit,
        )

        has_more = len(rows) > limit
        if has_more:
            rows = rows[:-1]

        items = []
        for row in rows:
            items.append({
                "callId": row["call_id"],
                "type": "call",
                "clientEpk": row["client_epk"],
                "clientFio": self._client_fio.for_api(
                    row["client_fio"], row["client_fio_encrypted"]
                ),
                "occurredAt": row["occurred_at"].isoformat(),
                "score": row["score"],
            })
        return _without_nulls({"items": items, "hasMore": has_more})

    async def dialog_report(self, call_id: str) -> dict:
        logger.info("Dialog GET received call_id=%s", call_id)
        report = await self._reports.get(call_id)
        if report is None:
            raise EntityNotFoundError("Отчёт не найден")
        logger.info("Dialog GET returned call_id=%s score=%s", call_id, report.score)

        if report.report_payload:
            return self._public(report.report_payload)
        raise EntityNotFoundError("Готовый payload отчёта не сформирован")

    async def _latest_value(self, manager_id: str, name: str):
        logger.info(
            "Dashboard GET manager_id=%s",
            manager_id,
        )
        value = await self._dashboards.latest_snapshot_value(manager_id, name)
        if value is None:
            raise EntityNotFoundError("Витрина менеджера за дату не сформирована")
        return value

    def _public(self, value):
        if isinstance(value, dict):
            result = {}
            encrypted = value.get("clientFioEncrypted", False)
            for key, item in value.items():
                if key == "clientFioEncrypted":
                    continue
                if key == "clientFio":
                    result[key] = self._client_fio.for_api(item, encrypted)
                else:
                    result[key] = self._public(item)
            return result
        if isinstance(value, list):
            return [self._public(item) for item in value]
        return "" if value is None else value


def _without_nulls(value):
    if value is None:
        return ""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            result[key] = _without_nulls(item)
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            result.append(_without_nulls(item))
        return result
    return value
