"""'Draft this': turn an opportunity into a first draft the team can edit and publish."""

import logging

from app.common.config import settings
from app.common.llm import LLMError, chat
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
    if settings.ai_enabled:
        try:
            data = chat(settings.prompt_model, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}])
            text = (data["choices"][0]["message"].get("content") or "").strip()
            if text:
                return {"markdown": text, "generated": True}
        except LLMError as exc:
            log.warning("Draft generation failed, using the outline: %s", exc)
    return {"markdown": _outline(project, opportunity), "generated": False}


def _outline(project: Project, opportunity: Opportunity) -> str:
    """Without an AI key: a structured outline the team can fill in."""
    return (
        f"# {opportunity.title}\n\n"
        f"**Goal:** {opportunity.recommended_action}\n\n"
        f"## Who {project.brand_name} is for\n[One paragraph: the buyer, their problem, and why {project.brand_name} fits.]\n\n"
        f"## How {project.brand_name} compares\n[A short, honest comparison table against the alternatives buyers ask AI about.]\n\n"
        "## Frequently asked questions\n[Answer the exact questions from this opportunity, one short paragraph each.]\n\n"
        "## Proof\n[Customer quotes, reviews, numbers you can stand behind.]\n"
    )
