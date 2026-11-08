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


EVIDENCE_LIMIT = 6000  # characters of evidence in the prompt: enough to be specific, small enough to stay cheap


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _evidence_sections(evidence: dict) -> dict[str, list[str]]:
    """The gap's evidence as short lines per section. Every line stands alone, so a cut never splits a quote."""
    questions = [q for q in _list(evidence.get("questions")) if isinstance(q, dict)]
    picked, pages = [], {}
    for q in questions:
        for w in (w for w in _list(q.get("winners")) if isinstance(w, dict) and w.get("name")):
            line = f"- For {q.get('text') or 'a buyer question'}: AI picked {w['name']}"
            if w.get("reason"):
                line += f" (summary: {w['reason']})"
            picked.append(line + (f', in its own words: "{w["quote"]}"' if w.get("quote") else ""))
    for p in [p for q in questions for p in _list(q.get("cited_pages"))] + _list(evidence.get("pages")):
        if isinstance(p, dict) and p.get("url"):
            pages.setdefault(p["url"], p.get("source_type"))
    return {
        "Why AI chose others": [f"- {x}" for x in _list(evidence.get("why")) if isinstance(x, str)],
        "How to tell it worked": [f"- {evidence['success_metric']}"] if isinstance(evidence.get("success_metric"), str) else [],
        "Steps already recommended": [f"- {x}" for x in _list(evidence.get("steps")) if isinstance(x, str)],
        "Who AI picked, with its own words": picked,
        "Pages AI read for these answers (exact URLs)": [f"- {u}" + (f" ({t})" if t else "") for u, t in pages.items()],
    }


def evidence_text(evidence) -> str:
    """The sections that fit in EVIDENCE_LIMIT. The short, decisive ones are filled first; a section is cut between lines."""
    sections = _evidence_sections(evidence if isinstance(evidence, dict) else {})
    room, kept = EVIDENCE_LIMIT, {}
    for title in ("Why AI chose others", "How to tell it worked", "Steps already recommended",
                  "Who AI picked, with its own words", "Pages AI read for these answers (exact URLs)"):
        kept[title] = []
        for line in sections[title]:
            if len(line) + 1 > room:
                break
            kept[title].append(line)
            room -= len(line) + 1
    order = ("Why AI chose others", "Who AI picked, with its own words", "Pages AI read for these answers (exact URLs)",
             "Steps already recommended", "How to tell it worked")
    return "\n\n".join(f"{t}:\n" + "\n".join(kept[t]) for t in order if kept[t])


def draft_for(project: Project, opportunity: Opportunity) -> dict:
    prompts = ", ".join((opportunity.evidence or {}).get("prompts", [])[:5]) if isinstance(opportunity.evidence, dict) else ""
    evidence = evidence_text(opportunity.evidence)
    user = (
        f"Brand: {project.brand_name} ({project.website})\nCategory: {project.category}\nMarket: {project.country}\n"
        f"About: {project.description or '-'}\n\nGap found: {opportunity.title}\n{opportunity.description}\n"
        f"Recommended action: {opportunity.recommended_action}\n"
        + (f"Buyer questions where AI leaves the brand out: {prompts}\n" if prompts else "")
        + (f"\nEvidence from the AI answers (quotes are the AI's words about rivals, not facts about {project.brand_name}):\n{evidence}\n" if evidence else "")
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
