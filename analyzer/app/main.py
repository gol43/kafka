import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_client import make_asgi_app

from app.agents.external_analyzer_agent import ExternalAnalyzerAgent
from app.agents.gigachat_provider.factory import create_llm_provider
from app.agents.prompt_analysis_agent import PromptAnalysisAgent
from app.agents.prompt_loader import PromptLoader
from app.api.callbacks import router as callback_router
from app.api.health import router as health_router
from app.api.manager import router as manager_router
from app.api.runs import router as runs_router
from app.config import get_settings
from app.database.repositories.analysis_task_repository import AnalysisTaskRepository
from app.database.repositories.dialog_repository import DialogRepository
from app.database.repositories.dashboard_repository import DashboardRepository
from app.services.analysis_worker import AnalysisWorker
from app.services.dialog_analysis_orchestrator import DialogAnalysisOrchestrator
from app.services.dialog_intake import DialogIntakeService
from app.services.dashboard_builder import DashboardBuilder
from app.services.dashboard_scheduler import DashboardScheduler
from app.services.manager_service import ManagerService
from app.services.prompt_dialog_analyzer import PromptDialogAnalyzer

settings = get_settings()
logging.basicConfig(level=settings.log_level)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    prompt_loader = PromptLoader(active_criteria_codes=settings.active_criteria_codes)
    provider = create_llm_provider(settings)

    dialog_repository = DialogRepository()
    task_repository = AnalysisTaskRepository()
    dashboard_repository = DashboardRepository()

    prompt_agent = PromptAnalysisAgent(
        prompt_loader,
        provider,
        log_responses=settings.log_llm_responses,
    )
    prompt_dialog_analyzer = PromptDialogAnalyzer(
        prompt_loader=prompt_loader,
        agent=prompt_agent,
        settings=settings,
    )
    external_analyzers = {}
    if settings.audio_analyzer_url:
        external_analyzers["audio"] = ExternalAnalyzerAgent(
            name="audio",
            base_url=settings.audio_analyzer_url,
            timeout_seconds=settings.external_analyzer_timeout_seconds,
        )
    if settings.faq_analyzer_url:
        external_analyzers["faq"] = ExternalAnalyzerAgent(
            name="faq",
            base_url=settings.faq_analyzer_url,
            timeout_seconds=settings.external_analyzer_timeout_seconds,
        )

    dialog_orchestrator = DialogAnalysisOrchestrator(
        repository=dialog_repository,
        prompt_analyzer=prompt_dialog_analyzer,
        external_analyzers=external_analyzers,
        settings=settings,
        positive_templates=prompt_loader.positive_templates,
    )
    worker = AnalysisWorker(
        settings=settings,
        tasks=task_repository,
        dialogs=dialog_repository,
        dialog_orchestrator=dialog_orchestrator,
    )
    dashboard_builder = DashboardBuilder(settings, dashboard_repository)
    scheduler = DashboardScheduler(settings, dashboard_builder)

    app.state.analysis_worker = worker
    app.state.dashboard_scheduler = scheduler
    app.state.dialog_intake = DialogIntakeService(
        settings,
        dialog_repository,
        worker,
    )
    app.state.manager_service = ManagerService(
        dialog_repository,
        dashboard_repository,
    )

    worker_task = asyncio.create_task(worker.run(), name="analysis-worker")
    scheduler.start()

    try:
        yield
    finally:
        scheduler.shutdown()
        await worker.stop()
        worker_task.cancel()
        await asyncio.gather(worker_task, return_exceptions=True)
        await asyncio.gather(
            *(agent.close() for agent in external_analyzers.values()),
            return_exceptions=True,
        )
        await provider.close()


app = FastAPI(title="Communication Quality Analyzer", lifespan=lifespan)
app.include_router(callback_router)
app.include_router(manager_router)
app.include_router(runs_router)
app.include_router(health_router)
app.mount("/metrics", make_asgi_app())
