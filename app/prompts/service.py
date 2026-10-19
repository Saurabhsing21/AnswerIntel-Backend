import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.billing.plans import entitlements
from app.billing.service import active_prompts
from app.common.config import settings
from app.common.llm import LLMError
from app.competitors.models import Competitor
from app.projects.models import Project
from app.prompts.generator import (
    LLMPromptGenerator,
    PromptGenerator,
    PromptInput,
    TemplatePromptGenerator,
    generate_prompts,
)
from app.prompts.models import Prompt, ScanPrompt

log = logging.getLogger(__name__)


def build_input(session: Session, project: Project) -> PromptInput:
    competitors = session.scalars(select(Competitor).where(Competitor.project_id == project.id)).all()
    return PromptInput(
        brand_name=project.brand_name,
        category=project.category,
        country=project.country,
        description=project.description,
        competitors=[competitor.name for competitor in competitors],
    )


class PromptDiscoveryService:
    def __init__(
        self,
        generator: PromptGenerator | None = None,
    ):
        self.generator = generator

    def _generate(self, data: PromptInput) -> tuple[list[dict], str]:
        if self.generator is not None:
            return generate_prompts(generator=self.generator, data=data), "template"
        if settings.ai_enabled:
            try:
                return generate_prompts(generator=LLMPromptGenerator(), data=data), "ai"
            except LLMError as exc:
                log.warning("Prompt Discovery Agent failed, using templates: %s", exc)
        return generate_prompts(generator=TemplatePromptGenerator(), data=data), "template"

    def generate_for_project(self, session: Session, project: Project) -> list[Prompt]:
        """Adds newly discovered prompts; existing ones (and user edits) are kept."""
        candidates, source = self._generate(build_input(session, project))
        existing = {
            text.strip().lower()
            for text in session.scalars(select(Prompt.text).where(Prompt.project_id == project.id))
        }
        active = session.scalar(
            select(func.count()).select_from(Prompt).where(Prompt.project_id == project.id, Prompt.is_active)
        ) or 0
        pool = entitlements(session, project.workspace_id).active_prompts
        pool_used = active_prompts(session, project.workspace_id)  # the plan's pool is shared by every project
        created: list[Prompt] = []
        for candidate in candidates:
            key = candidate["text"].strip().lower()
            if key in existing:
                continue
            existing.add(key)
            prompt = Prompt(
                project_id=project.id,
                text=candidate["text"].strip(),
                category=candidate["category"],
                intent=candidate["intent"],
                importance=candidate.get("importance"),
                source=source,
                # Respect the plan's prompt pool and the per-project ceiling; extras are kept inactive for review.
                is_active=pool_used < pool and active < settings.max_active_prompts,
            )
            active += int(prompt.is_active)
            pool_used += int(prompt.is_active)
            session.add(prompt)
            created.append(prompt)
        session.flush()
        return created

    def snapshot_for_scan(self, session: Session, project: Project, scan_id: int) -> list[ScanPrompt]:
        """Freezes the active prompts into the scan so history stays immutable."""
        prompts = session.scalars(
            select(Prompt).where(Prompt.project_id == project.id, Prompt.is_active).order_by(Prompt.id)
        ).all()
        snapshots = [
            ScanPrompt(scan_id=scan_id, prompt_id=p.id, text=p.text, category=p.category, intent=p.intent)
            for p in prompts
        ]
        session.add_all(snapshots)
        session.flush()
        return snapshots
