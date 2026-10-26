"""Suggest a brand's top competitors, so founders don't have to know them up front.

Asks a model with live web search; without an AI key it returns clearly-marked samples so the setup flow still works.
"""

import json
import logging
import re
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, ValidationError

from app.common.config import settings
from app.common.llm import LLMError, chat

log = logging.getLogger(__name__)

MAX_SUGGESTIONS = 8
SAMPLES = [
    ("Kiteline", "kiteline.io", ""),
    ("Vantor", "vantor.app", ""),
    ("Northwind", "northwind.dev", ""),
    ("Brightloop", "brightloop.co", ""),
]

SYSTEM = """You find a company's direct competitors: products a buyer would compare it with before choosing.
Search the web. Prefer companies that AI assistants and review sites commonly recommend in this category and market.
Return JSON: {"competitors": [{"name", "website", "reason"}]} with up to 8 entries, most important first.
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
    """`exclude`: lower-case names and domains already tracked. Returns {"suggestions": [...], "sample": bool}."""
    own = _domain(website)
    if not settings.ai_enabled:
        rows = [{"name": n, "website": f"https://{w}", "reason": r} for n, w, r in SAMPLES]
        return {"suggestions": [r for r in rows if r["name"].lower() not in exclude], "sample": True}
    user = (
        f"Company: {brand} ({website})\nCategory: {category}\nMarket: {country}\n"
        f"About: {description or 'not given'}"
    )
    try:
        data = chat(settings.analysis_model, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                    json_mode=True, web_search=True)
        content = (data["choices"][0]["message"].get("content") or "").strip()
        content = re.sub(r"^```(?:json)?|```$", "", content).strip()
        parsed = Suggestions.model_validate(json.loads(content))
    except (LLMError, json.JSONDecodeError, ValidationError, KeyError, IndexError):
        log.warning("Competitor suggestion failed for %s", brand, exc_info=True)
        return {"suggestions": [], "sample": False}

    seen: set[str] = set()
    out = []
    for s in parsed.competitors:
        domain = _domain(s.website)
        key = s.name.strip().lower()
        if not domain or "." not in domain or domain == own or key == brand.lower() or key in exclude or domain in exclude or key in seen:
            continue
        seen.add(key)
        out.append({"name": s.name.strip(), "website": f"https://{domain}", "reason": s.reason.strip()})
    return {"suggestions": out[:MAX_SUGGESTIONS], "sample": False}
