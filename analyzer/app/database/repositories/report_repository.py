import uuid
from datetime import UTC, date, datetime

from sqlalchemy import distinct, select, update

from app.database.connection import session_scope
from app.database.models import (
    DailyReport,
    Dialog,
    FourWeekReport,
    QuarterlyReport,
    WeeklyReport,
)
from app.schemas.entities import AggregateReportEntity, DialogEntity

ReportModel = DailyReport | WeeklyReport | FourWeekReport | QuarterlyReport

REPORT_MODELS = {
    "daily": DailyReport,
    "weekly": WeeklyReport,
    "four_week": FourWeekReport,
    "quarterly": QuarterlyReport,
}


class ReportRepository:
    """SQL-операции четырёх явно разделённых типов агрегированных отчётов."""

    async def daily_sources(
        self,
        manager_id: str,
        work_date: date,
    ) -> list[DialogEntity]:
        """Возвращает ещё не использованные завершённые диалоги рабочего дня."""

        async with session_scope() as session:
            dialogs = list(
                (
                    await session.scalars(
                        select(Dialog)
                        .where(
                            Dialog.manager_id == manager_id,
                            Dialog.work_date == work_date,
                            Dialog.analysis_status == "completed",
                            Dialog.daily_report_id.is_(None),
                        )
                        .order_by(Dialog.created_at)
                    )
                ).all()
            )
            return [DialogEntity.model_validate(dialog) for dialog in dialogs]

    async def period_sources(
        self,
        manager_id: str,
        child_type: str,
        start: date,
        end: date,
    ) -> list[AggregateReportEntity]:
        """Возвращает завершённые отчёты предыдущего уровня."""

        model = REPORT_MODELS[child_type]
        conditions = [model.manager_id == manager_id, model.status == "completed"]

        if child_type == "daily":
            conditions.extend(
                [
                    model.report_date >= start,
                    model.report_date <= end,
                    model.weekly_report_id.is_(None),
                ]
            )
            order_column = model.report_date
        elif child_type == "weekly":
            conditions.extend(
                [
                    model.period_start >= start,
                    model.period_end <= end,
                    model.four_week_report_id.is_(None),
                ]
            )
            order_column = model.period_start
        else:
            conditions.extend(
                [
                    model.period_start >= start,
                    model.period_end <= end,
                    model.quarterly_report_id.is_(None),
                ]
            )
            order_column = model.period_start

        async with session_scope() as session:
            reports = list(
                (
                    await session.scalars(
                        select(model).where(*conditions).order_by(order_column)
                    )
                ).all()
            )
            return [self._to_entity(report, child_type) for report in reports]

    async def save_completed(
        self,
        *,
        report_type: str,
        manager_id: str,
        start: date,
        end: date,
        report_version: str,
        score_sum: float,
        communications_count: int,
        summary: str,
        details: dict,
        source_ids: list[str],
    ) -> AggregateReportEntity:
        """Сохраняет отчёт и помечает его источники использованными."""

        model = REPORT_MODELS[report_type]
        async with session_scope() as session:
            report = await self._find_report(
                session,
                report_type,
                manager_id,
                start,
                end,
                report_version,
                lock=True,
            )
            if report is None:
                values = {
                    "manager_id": manager_id,
                    "status": "processing",
                    "report_version": report_version,
                }
                if report_type == "daily":
                    values["report_date"] = start
                else:
                    values["period_start"] = start
                    values["period_end"] = end
                report = model(**values)
                session.add(report)
                await session.flush()

            report.status = "completed"
            report.score_sum = score_sum
            report.communications_count = communications_count
            report.q_score = score_sum / communications_count
            report.summary = summary
            report.details = details
            report.completed_at = datetime.now(UTC)

            await self._bind_sources(session, report_type, report.id, source_ids)
            self._set_source_ids(report, report_type, source_ids)
            return self._to_entity(report, report_type)

    async def mark_failed(
        self,
        *,
        report_type: str,
        manager_id: str,
        start: date,
        end: date,
        report_version: str,
        error_code: str,
    ) -> None:
        """Создаёт либо обновляет техническую запись неуспешного отчёта."""

        model = REPORT_MODELS[report_type]
        async with session_scope() as session:
            report = await self._find_report(
                session,
                report_type,
                manager_id,
                start,
                end,
                report_version,
                lock=True,
            )
            if report is None:
                values = {
                    "manager_id": manager_id,
                    "status": "failed",
                    "report_version": report_version,
                    "error_code": error_code,
                }
                if report_type == "daily":
                    values["report_date"] = start
                else:
                    values["period_start"] = start
                    values["period_end"] = end
                session.add(model(**values))
                return

            report.status = "failed"
            report.error_code = error_code

    async def get_completed_daily(
        self,
        manager_id: str,
        report_date: date,
    ) -> AggregateReportEntity | None:
        """Возвращает только готовый дневной отчёт."""

        async with session_scope() as session:
            report = await session.scalar(
                select(DailyReport).where(
                    DailyReport.manager_id == manager_id,
                    DailyReport.report_date == report_date,
                    DailyReport.status == "completed",
                )
            )
            return self._to_entity(report, "daily") if report is not None else None

    async def completed_dialog_scores(
        self,
        daily_report_id,
    ) -> list[tuple[str, float | None]]:
        """Возвращает звонки, вошедшие в конкретный дневной отчёт."""

        async with session_scope() as session:
            rows = (
                await session.execute(
                    select(Dialog.call_id, Dialog.q_score).where(
                        Dialog.daily_report_id == daily_report_id,
                        Dialog.analysis_status == "completed",
                    )
                )
            ).all()
            return [(call_id, q_score) for call_id, q_score in rows]

    async def completed_daily_dates(
        self,
        manager_id: str,
        from_date: date,
        to_date: date,
    ) -> list[date]:
        """Возвращает даты доступных дневных отчётов менеджера."""

        async with session_scope() as session:
            return list(
                (
                    await session.scalars(
                        select(DailyReport.report_date)
                        .where(
                            DailyReport.manager_id == manager_id,
                            DailyReport.status == "completed",
                            DailyReport.report_date >= from_date,
                            DailyReport.report_date <= to_date,
                        )
                        .order_by(DailyReport.report_date)
                    )
                ).all()
            )

    async def managers_with_completed_dialogs(self, work_date: date) -> list[str]:
        """Находит менеджеров, для которых можно строить дневной отчёт."""

        async with session_scope() as session:
            return list(
                (
                    await session.scalars(
                        select(distinct(Dialog.manager_id)).where(
                            Dialog.work_date == work_date,
                            Dialog.analysis_status == "completed",
                            Dialog.daily_report_id.is_(None),
                        )
                    )
                ).all()
            )

    async def managers_with_completed_reports(
        self,
        report_type: str,
        start: date | None = None,
        end: date | None = None,
    ) -> list[str]:
        """Находит менеджеров с готовыми источниками нужного уровня."""

        model = REPORT_MODELS[report_type]
        conditions = [model.status == "completed"]
        if report_type == "daily":
            if start is not None:
                conditions.append(model.report_date >= start)
            if end is not None:
                conditions.append(model.report_date <= end)
        else:
            if start is not None:
                conditions.append(model.period_start >= start)
            if end is not None:
                conditions.append(model.period_end <= end)

        async with session_scope() as session:
            return list(
                (
                    await session.scalars(
                        select(distinct(model.manager_id)).where(*conditions)
                    )
                ).all()
            )

    async def unconsumed_reports(
        self,
        manager_id: str,
        report_type: str,
    ) -> list[AggregateReportEntity]:
        """Возвращает отчёты, ещё не вошедшие в следующий уровень."""

        if report_type == "weekly":
            model = WeeklyReport
            parent_column = WeeklyReport.four_week_report_id
        elif report_type == "four_week":
            model = FourWeekReport
            parent_column = FourWeekReport.quarterly_report_id
        else:
            raise ValueError(f"Для {report_type} нет следующего уровня")

        async with session_scope() as session:
            reports = list(
                (
                    await session.scalars(
                        select(model)
                        .where(
                            model.manager_id == manager_id,
                            model.status == "completed",
                            parent_column.is_(None),
                        )
                        .order_by(model.period_start)
                    )
                ).all()
            )
            return [self._to_entity(report, report_type) for report in reports]

    async def _find_report(
        self,
        session,
        report_type: str,
        manager_id: str,
        start: date,
        end: date,
        report_version: str,
        *,
        lock: bool,
    ) -> ReportModel | None:
        model = REPORT_MODELS[report_type]
        conditions = [
            model.manager_id == manager_id,
            model.report_version == report_version,
        ]
        if report_type == "daily":
            conditions.append(model.report_date == start)
        else:
            conditions.extend([model.period_start == start, model.period_end == end])

        statement = select(model).where(*conditions)
        if lock:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    async def _bind_sources(
        self,
        session,
        report_type: str,
        report_id,
        source_ids: list[str],
    ) -> None:
        if report_type == "daily":
            model, key, parent = Dialog, Dialog.call_id, "daily_report_id"
        elif report_type == "weekly":
            model, key, parent = DailyReport, DailyReport.id, "weekly_report_id"
        elif report_type == "four_week":
            model, key, parent = WeeklyReport, WeeklyReport.id, "four_week_report_id"
        else:
            model, key, parent = (
                FourWeekReport,
                FourWeekReport.id,
                "quarterly_report_id",
            )

        database_ids = source_ids
        if report_type != "daily":
            database_ids = [uuid.UUID(source_id) for source_id in source_ids]

        await session.execute(
            update(model).where(key.in_(database_ids)).values({parent: report_id})
        )

    @staticmethod
    def _set_source_ids(
        report: ReportModel, report_type: str, source_ids: list[str]
    ) -> None:
        if report_type == "daily":
            report.source_call_ids = source_ids
        elif report_type == "weekly":
            report.source_daily_report_ids = source_ids
        elif report_type == "four_week":
            report.source_weekly_report_ids = source_ids
        else:
            report.source_four_week_report_ids = source_ids

    @staticmethod
    def _to_entity(
        report: ReportModel,
        report_type: str,
    ) -> AggregateReportEntity:
        if report_type == "daily":
            period_start = report.report_date
            period_end = report.report_date
        else:
            period_start = report.period_start
            period_end = report.period_end

        return AggregateReportEntity(
            id=report.id,
            report_type=report_type,
            manager_id=report.manager_id,
            period_start=period_start,
            period_end=period_end,
            q_score=report.q_score,
            score_sum=report.score_sum,
            communications_count=report.communications_count,
            summary=report.summary,
            details=report.details,
        )
