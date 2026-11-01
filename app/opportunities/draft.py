"""'Draft this': turn an opportunity into a first draft the team can edit and publish."""

import logging

from app.common.config import settings
from app.common.errors import ai_unavailable
from app.common.llm import LLMError, chat
from app.costs.service import cost_scope
from app.opportunities.models import Opportunity
from app.projects.models import Project

log = logging.getLogger(__name__)

SYSTEM = """You write a first draft for a small company's website or outreach, to make AI assistants more likely to
recommend the brand. Write in plain, concrete language, no hype, no invented facts, statistics, prices or customer
names: where a fact is needed, leave a [placeholder] for the team to fill in. Output Markdown only."""


def draft_for(project: Project, opportunity: Opportunity) -> dict:
    prompts = ", ".join((opportunity.evidence or {}).get("prompts", [])[:5]) if isinstance(opportunity.evidence, dict) else ""
    user = (
        f"Brand: {project.brand_name} ({project.website})\nCategory: {project.category}\nMarket: {project.country}\n"
        f"About: {project.description or '-'}\n\nGap found: {opportunity.title}\n{opportunity.description}\n"
        f"Recommended action: {opportunity.recommended_action}\n"
        + (f"Buyer questions where AI leaves the brand out: {prompts}\n" if prompts else "")
        + "\nWrite the draft that carries out the recommended action."
    )
    try:
        with cost_scope(purpose="draft", workspace_id=project.workspace_id, project_id=project.id, user_id=project.user_id):
            data = chat(settings.prompt_model, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}])
        text = (data["choices"][0]["message"].get("content") or "").strip()
    except (LLMError, KeyError, IndexError):
        log.warning("Draft generation failed", exc_info=True)
        raise ai_unavailable()
    if not text:
        raise ai_unavailable()
    return {"markdown": text}
