from sqlalchemy import select
from sqlalchemy.orm import Session

from app.competitors.models import Competitor
from app.projects.models import Project
from app.prompts.generator import (
    PromptGenerator,
    PromptInput,
    generate_prompts,
)
from app.prompts.models import ScanPrompt


class PromptDiscoveryService:

    def __init__(
        self,
        generator: PromptGenerator,
    ):
        self.generator = generator

    def generate_for_scan(
        self,
        session: Session,
        project: Project,
        scan_id: int,
    ) -> list[ScanPrompt]:

        competitors = session.scalars(
            select(Competitor)
            .where(Competitor.project_id == project.id)
        ).all()

        prompt_input = PromptInput(
            brand_name=project.brand_name,
            category=project.category,
            country=project.country,
            description=project.description,
            competitors=[competitor.name for competitor in competitors],
        )

        prompts = generate_prompts(
            generator=self.generator,
            data=prompt_input,
        )

        scan_prompts = []

        for prompt in prompts:
            scan_prompt = ScanPrompt(
                scan_id=scan_id,
                text=prompt["text"],
                category=prompt["category"],
                intent=prompt["intent"],
            )

            session.add(scan_prompt)
            scan_prompts.append(scan_prompt)

        session.flush()

        return scan_prompts