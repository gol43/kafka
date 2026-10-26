import logging
from app.database.repositories.dialog_repository import DialogRepository
from app.database.repositories.dashboard_repository import DashboardRepository
from app.exceptions import EntityNotFoundError

logger = logging.getLogger(__name__)


class ManagerService:
    """Собирает ответы API исключительно из завершённых отчётов."""

    def __init__(
        self,
        dialogs: DialogRepository,
        dashboards: DashboardRepository,
    ) -> None:
        self._dialogs = dialogs
        self._dashboards = dashboards

    async def dashboard_block(self, manager_id: str, block: str) -> dict | list:
        payload = await self._dashboards.latest_dashboard(manager_id)
        if payload is None:
            raise EntityNotFoundError("Витрина менеджера не сформирована")
        return payload[block]

    async def client_metric(
        self,
        manager_id: str,
        client_epk: str,
        metric_code: str,
    ) -> dict:
        payload = await self._dashboards.latest_client_metric(
            manager_id,
            client_epk,
            metric_code,
        )
        if payload is None:
            raise EntityNotFoundError("Детализация клиента не найдена")
        return payload

    async def metric_detail(self, manager_id: str, metric_code: str) -> dict:
        payload = await self._dashboards.latest_manager_metric(
            manager_id,
            metric_code,
        )
        if payload is None:
            raise EntityNotFoundError("Детализация метрики не найдена")
        return payload

    async def dialog_report(self, call_id: str) -> dict:
        logger.info("Dialog GET received call_id=%s", call_id)
        dialog = await self._dialogs.get_completed(call_id)
        if dialog is None:
            logger.info("Dialog GET not found call_id=%s", call_id)
            raise EntityNotFoundError("Отчёт не найден")

        response = dialog.dialog_report
        logger.info(
            "Dialog GET returned call_id=%s score=%s criteria=%s",
            call_id,
            dialog.q_score,
            dialog.deviations_count,
        )
        return response
