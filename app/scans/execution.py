from sqlalchemy import select
from sqlalchemy.orm import Session

from app.providers.base import AIProvider, AIResponse
from app.providers.registry import ModelRegistry
from app.prompts.models import ScanPrompt
from app.providers.response_model import AIResponseRecord


class ScanExecutionService:

    def __init__(
        self,
        provider: AIProvider,
        model_registry: ModelRegistry,
    ):
        self.provider = provider
        self.model_registry = model_registry

    def execute_scan(
        self,
        session: Session,
        scan_id: int,
    ) -> list[AIResponse]:

        prompts = session.scalars(
            select(ScanPrompt)
            .where(ScanPrompt.scan_id == scan_id)
            .order_by(ScanPrompt.id)
        ).all()

        responses = []

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