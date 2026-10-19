from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.billing.plans import engines_for, entitlements, require_active, require_room
from app.billing.service import scans_today
from app.common.config import settings
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
        ent = entitlements(session, project.workspace_id)
        require_active(ent)
        running = session.scalar(
            select(Scan).where(Scan.project_id == project.id, Scan.status.in_(ACTIVE_STATUSES))
        )
        if running:
            raise AppError(409, "SCAN_ALREADY_RUNNING", "A scan is already running for this project.")
        recent = session.scalar(
            select(func.count()).select_from(Scan).where(
                Scan.project_id == project.id, Scan.created_at >= datetime.now(timezone.utc) - timedelta(days=1)
            )
        ) or 0
        if recent >= settings.max_scans_per_day:
            raise AppError(429, "SCAN_LIMIT_REACHED", "Daily scan limit reached for this project. Try again tomorrow.")
        message = f"Your plan includes {ent.scans_per_day} scans a day across the workspace. Try again tomorrow."
        require_room(ent, "scans_per_day", scans_today(session, project.workspace_id), message, "SCAN_LIMIT_REACHED", 429)
        active = session.scalar(
            select(func.count()).select_from(Prompt).where(Prompt.project_id == project.id, Prompt.is_active)
        ) or 0
        if not active:
            raise AppError(409, "NO_ACTIVE_PROMPTS", "Generate or add prompts before starting a scan.")

        scan = Scan(project_id=project.id, status="queued")
        session.add(scan)
        session.flush()
        snapshots = self.prompt_discovery.snapshot_for_scan(session, project, scan.id)
        scan.total_runs = len(snapshots) * len(engines_for(self.model_registry.get_all(), ent))
        return scan

    def run(self, scan_id: int) -> None:
        ScanExecutionService(provider=self.provider, model_registry=self.model_registry).run(scan_id)
