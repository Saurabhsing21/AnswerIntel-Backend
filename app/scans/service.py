from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.projects.models import Project
from app.prompts.generator import TemplatePromptGenerator
from app.prompts.service import PromptDiscoveryService
from app.scans.models import Scan


class ScanService:

    def __init__(self):
        self.prompt_discovery = PromptDiscoveryService(
            generator=TemplatePromptGenerator()
        )

    def create_scan(
        self,
        session: Session,
        project: Project,
    ) -> Scan:

        # 1. Create scan
        scan = Scan(
            project_id=project.id,
            status="pending",
        )

        session.add(scan)
        session.flush()

        # 2. Mark scan as running
        scan.status = "running"
        scan.started_at = datetime.now(timezone.utc)

        # 3. Generate prompts for this scan
        self.prompt_discovery.generate_for_scan(
            session=session,
            project=project,
            scan_id=scan.id,
        )

        # For now we stop here.
        #
        # Later:
        #
        # prompts
        #    ↓
        # AI providers
        #    ↓
        # raw responses
        #    ↓
        # analysis
        #    ↓
        # metrics
        #    ↓
        # opportunities

        return scan