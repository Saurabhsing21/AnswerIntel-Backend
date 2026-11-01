"""Suggest a brand's top competitors, so founders don't have to know them up front.

Asks a model with live web search. If the AI service is unavailable the caller gets an error, never made-up names.
"""

import json
import logging
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, ValidationError

from app.common.config import settings
from app.common.errors import ai_unavailable
from app.common.llm import LLMError, chat

log = logging.getLogger(__name__)

MAX_SUGGESTIONS = 8

SYSTEM = """You find a company's direct competitors: products a buyer would compare it with before choosing.
Search the web. Prefer companies that AI assistants and review sites commonly recommend in this category and market.
Return JSON: {"competitors": [{"name", "website", "reason"}]} with exactly 8 entries, most important first (fewer only if fewer real competitors exist).
- name: the brand name only. website: its homepage domain, like example.com.
- reason: under 15 words, why buyers compare them (same audience, same job).
Never include the company itself. Don't invent companies; return fewer if unsure."""


class Suggestion(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    website: str = Field(min_length=3, max_length=500)
    reason: str = Field(default="", max_length=200)


class Suggestions(BaseModel):
    competitors: list[Suggestion] = Field(max_length=20)


def _domain(url: str) -> str:
    host = urlsplit(url if "://" in url else f"https://{url}").netloc.lower()
    return host.removeprefix("www.")


def suggest_competitors(brand: str, website: str, category: str, country: str, description: str | None, exclude: set[str]) -> dict:
    """`exclude`: lower-case names and domains already tracked. Returns {"suggestions": [...]}."""
    own = _domain(website)
    user = (
        f"Company: {brand} ({website})\nCategory: {category}\nMarket: {country}\n"
        f"About: {description or 'not given'}"
    )
    try:
        data = chat(settings.competitor_model, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                    web_search=True)  # no JSON mode: OpenAI rejects it alongside web search
        content = (data["choices"][0]["message"].get("content") or "").strip()
        content = content[content.find("{"):content.rfind("}") + 1]  # searched answers can wrap the JSON in prose
        parsed = Suggestions.model_validate(json.loads(content))
    except (LLMError, json.JSONDecodeError, ValidationError, KeyError, IndexError):
        log.warning("Competitor suggestion failed for %s", brand, exc_info=True)
        raise ai_unavailable()

    seen: set[str] = set()
    out = []
    for s in parsed.competitors:
        domain = _domain(s.website)
        key = s.name.strip().lower()
        if not domain or "." not in domain or domain == own or key == brand.lower() or key in exclude or domain in exclude or key in seen:
            continue
        seen.add(key)
        out.append({"name": s.name.strip(), "website": f"https://{domain}", "reason": s.reason.strip()})
    return {"suggestions": out[:MAX_SUGGESTIONS]}
