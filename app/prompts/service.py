import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.billing.plans import entitlements
from app.billing.service import active_prompts, pool_holders
from app.common.config import settings
from app.common.errors import ai_unavailable
from app.common.llm import LLMError
from app.competitors.models import Competitor
from app.costs.service import cost_scope
from app.projects.models import Project
from app.prompts.generator import (
    LLMPromptGenerator,
    PromptGenerator,
    PromptInput,
    generate_prompts,
)
from app.prompts.models import Prompt, ScanPrompt

log = logging.getLogger(__name__)


def build_input(session: Session, project: Project) -> PromptInput:
    competitors = session.scalars(select(Competitor).where(Competitor.project_id == project.id)).all()
    return PromptInput(
        brand_name=project.brand_name.strip(),
        category=project.category.strip(),
        country=project.country.strip(),
        description=project.description,
        competitors=[competitor.name.strip() for competitor in competitors],
    )


def pool_full_details(session: Session, workspace_id, limit: int) -> dict:
    """Who holds the plan's shared question pool, for the error and notice shown when it is full."""
    return {"holders": pool_holders(session, workspace_id), "limit": limit}


def pool_full_message(details: dict, current_project_id=None) -> str:
    holders, limit = details["holders"], details["limit"]
    if len(holders) == 1:
        h = holders[0]
        where = "Turn some off" if h["project_id"] == str(current_project_id) else "Turn some off there"
        return f"{h['brand']} is using all {limit} of your plan's questions. {where}, or upgrade."
    names = ", ".join(f"{h['brand']} ({h['active']})" for h in holders)
    return f"Your projects are using all {limit} of your plan's questions: {names}. Turn some off, or upgrade."


class PromptDiscoveryService:
    def __init__(
        self,
        generator: PromptGenerator | None = None,
    ):
        self.generator = generator

    def _generate(self, data: PromptInput) -> tuple[list[dict], str]:
        if self.generator is not None:
            return generate_prompts(generator=self.generator, data=data), "template"
        try:
            return generate_prompts(generator=LLMPromptGenerator(), data=data), "ai"
        except LLMError as exc:
            log.warning("Prompt Discovery Agent failed: %s", exc)
            raise ai_unavailable()

    def suggest(self, session: Session, project: Project, instructions: str, count: int) -> list[dict]:
        """New prompts written to the user's instructions, not saved: they pick which to keep."""
        data = build_input(session, project)
        data.instructions = instructions
        try:
            with cost_scope(purpose="question_writing", workspace_id=project.workspace_id, project_id=project.id, user_id=project.user_id):
                candidates = generate_prompts(generator=LLMPromptGenerator(count=count), data=data)
        except LLMError as exc:
            log.warning("Instructed prompt generation failed: %s", exc)
            raise ai_unavailable()
        existing = {t.strip().lower() for t in session.scalars(select(Prompt.text).where(Prompt.project_id == project.id))}
        fresh = []
        for c in candidates:
            key = c["text"].strip().lower()
            if key not in existing:
                existing.add(key)
                fresh.append({"text": c["text"].strip(), "category": c["category"], "intent": c["intent"], "importance": c.get("importance")})
        return fresh[:count]

    def add_many(self, session: Session, project: Project, items: list[dict]) -> list[Prompt]:
        """Saves the prompts the user accepted. Duplicates are skipped; past the plan's pool they are added switched off."""
        existing = {t.strip().lower() for t in session.scalars(select(Prompt.text).where(Prompt.project_id == project.id))}
        active = session.scalar(
            select(func.count()).select_from(Prompt).where(Prompt.project_id == project.id, Prompt.is_active)
        ) or 0
        pool = entitlements(session, project.workspace_id).active_prompts
        pool_used = active_prompts(session, project.workspace_id)
        created: list[Prompt] = []
        for item in items:
            key = item["text"].strip().lower()
            if key in existing:
                continue
            existing.add(key)
            prompt = Prompt(
                project_id=project.id, text=item["text"].strip(), category=item["category"], intent=item["intent"],
                importance=item.get("importance"), source="ai",
                is_active=pool_used < pool and active < settings.max_active_prompts,
            )
            active += int(prompt.is_active)
            pool_used += int(prompt.is_active)
            session.add(prompt)
            created.append(prompt)
        session.flush()
        return created

    def generate_for_project(self, session: Session, project: Project) -> list[Prompt]:
        """Adds newly discovered prompts; existing ones (and user edits) are kept."""
        with cost_scope(purpose="question_writing", workspace_id=project.workspace_id, project_id=project.id, user_id=project.user_id):
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

    def snapshot_for_scan(self, session: Session, project: Project, scan_id: int, prompt_ids: list[int] | None = None) -> list[ScanPrompt]:
        """Freezes the active prompts (or just `prompt_ids`, for a re-test) into the scan so history stays immutable."""
        chosen = Prompt.id.in_(prompt_ids) if prompt_ids else Prompt.is_active
        prompts = session.scalars(
            select(Prompt).where(Prompt.project_id == project.id, chosen).order_by(Prompt.id)
        ).all()
        snapshots = [
            ScanPrompt(scan_id=scan_id, prompt_id=p.id, text=p.text, category=p.category, intent=p.intent, engines=p.engines)
            for p in prompts
        ]
        session.add_all(snapshots)
        session.flush()
        return snapshots
