from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.errors import AppError
from app.projects.models import Project
from app.prompts.models import Prompt
from app.prompts.service import PromptDiscoveryService
from app.providers.base import AIProvider
from app.providers.registry import ModelRegistry
from app.scans.execution import ScanExecutionService
from app.scans.models import ACTIVE_STATUSES, Scan


class ScanService:
    def __init__(
        self,
        provider: AIProvider | None = None,
        model_registry: ModelRegistry | None = None,
    ):
        self.prompt_discovery = PromptDiscoveryService()
        self.model_registry = model_registry or ModelRegistry()
        self.provider = provider

    def start_scan(self, session: Session, project: Project) -> Scan:
        running = session.scalar(
            select(Scan).where(Scan.project_id == project.id, Scan.status.in_(ACTIVE_STATUSES))
        )
        if running:
            raise AppError(409, "SCAN_ALREADY_RUNNING", "A scan is already running for this project.")
        active = session.scalar(
            select(func.count()).select_from(Prompt).where(Prompt.project_id == project.id, Prompt.is_active)
        ) or 0
        if not active:
            raise AppError(409, "NO_ACTIVE_PROMPTS", "Generate or add prompts before starting a scan.")

        scan = Scan(project_id=project.id, status="queued")
        session.add(scan)
        session.flush()
        snapshots = self.prompt_discovery.snapshot_for_scan(session, project, scan.id)
        scan.total_runs = len(snapshots) * len(self.model_registry.get_all())
        return scan

    def run(self, scan_id: int) -> None:
        ScanExecutionService(provider=self.provider, model_registry=self.model_registry).run(scan_id)
