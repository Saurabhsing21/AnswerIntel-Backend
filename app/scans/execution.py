from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.base import AnalysisContext
from app.analysis.persistence import save_analysis
from app.analysis.service import ResponseAnalysisService
from app.competitors.models import Competitor
from app.projects.models import Project
from app.providers.base import AIProvider, AIResponse
from app.providers.registry import ModelRegistry
from app.providers.response_model import AIResponseRecord
from app.prompts.models import ScanPrompt
from app.scans.models import Scan


class ScanExecutionService:

    def __init__(
        self,
        provider: AIProvider,
        model_registry: ModelRegistry,
    ):
        self.provider = provider
        self.model_registry = model_registry
        self.analysis_service = ResponseAnalysisService()

    def execute_scan(
        self,
        session: Session,
        scan_id: int,
    ) -> list[AIResponse]:
        scan = session.get(Scan, scan_id)
        project = session.get(Project, scan.project_id)
        competitors = session.scalars(
            select(Competitor).where(Competitor.project_id == project.id)
        ).all()
        context = AnalysisContext(
            brand_name=project.brand_name,
            competitors=[
                {"id": competitor.id, "name": competitor.name}
                for competitor in competitors
            ],
        )

        prompts = session.scalars(
            select(ScanPrompt)
            .where(ScanPrompt.scan_id == scan_id)
            .order_by(ScanPrompt.id)
        ).all()

        responses: list[AIResponse] = []

        for prompt in prompts:
            for model_config in self.model_registry.get_all():
                response = self.provider.ask(
                    prompt=prompt.text,
                    model=model_config.model,
                )

                record = AIResponseRecord(
                    scan_id=scan_id,
                    scan_prompt_id=prompt.id,
                    provider=response.provider,
                    model=response.model,
                    prompt=response.prompt,
                    response_text=response.text,
                    raw_response=response.raw_response,
                )
                session.add(record)
                session.flush()

                result = self.analysis_service.analyze(
                    response.text,
                    context,
                )
                save_analysis(session, record.id, result)
                responses.append(response)

        session.flush()
        return responses
