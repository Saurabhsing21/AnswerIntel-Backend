from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.projects.models import Project
from app.prompts.generator import TemplatePromptGenerator
from app.prompts.service import PromptDiscoveryService
from app.providers.base import AIProvider
from app.providers.fake import FakeAIProvider
from app.providers.registry import ModelRegistry
from app.scans.execution import ScanExecutionService
from app.scans.models import Scan


class ScanService:

    def __init__(
        self,
        provider: AIProvider | None = None,
        model_registry: ModelRegistry | None = None,
    ):
        self.prompt_discovery = PromptDiscoveryService(
            generator=TemplatePromptGenerator()
        )
        self.execution = ScanExecutionService(
            provider=provider or FakeAIProvider(),
            model_registry=model_registry or ModelRegistry(),
        )

    def create_scan(
        self,
        session: Session,
        project: Project,
    ) -> Scan:
        scan = Scan(
            project_id=project.id,
            status="pending",
        )

        session.add(scan)
        session.flush()

        scan.status = "running"
        scan.started_at = datetime.now(timezone.utc)

        self.prompt_discovery.generate_for_scan(
            session=session,
            project=project,
            scan_id=scan.id,
        )

        self.execution.execute_scan(
            session=session,
            scan_id=scan.id,
        )

        scan.status = "completed"
        scan.completed_at = datetime.now(timezone.utc)

        return scan
