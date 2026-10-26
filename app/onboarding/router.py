"""New-project helpers that run before the project exists, so leaving setup half-way leaves nothing behind."""

import html
import json
import logging
import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.auth.dependencies import get_current_user
from app.common.config import settings
from app.common.llm import LLMError, chat
from app.common.safe_http import safe_get
from app.competitors.suggest import suggest_competitors
from app.users.models import User

log = logging.getLogger(__name__)
router = APIRouter(prefix="/onboarding", tags=["Onboarding"])


class Brand(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    brand_name: str = Field(min_length=1, max_length=255)
    website: str = Field(min_length=3, max_length=500)
    category: str = Field(min_length=1, max_length=255)
    country: str = Field(min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=2000)


@router.post("/competitors")
def competitors(payload: Brand, current_user: User = Depends(get_current_user)):
    return suggest_competitors(payload.brand_name, payload.website, payload.category, payload.country, payload.description, set())


def _meta(page: str, *names: str) -> str | None:
    for name in names:
        m = re.search(rf'<meta[^>]+(?:property|name)=["\']{name}["\'][^>]+content=["\']([^"\']+)', page, re.I) or re.search(
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{name}["\']', page, re.I)
        if m:
            return html.unescape(m.group(1)).strip()
    return None


def _categories(name: str | None, description: str | None) -> list[str]:
    """Three short category phrases a buyer would search for. Needs an AI key; empty otherwise."""
    if not settings.ai_enabled or not (name or description):
        return []
    try:
        data = chat(settings.analysis_model, [
            {"role": "system", "content": 'Name the product category of this company the way a buyer searches for it, e.g. "CRM software for startups". Return JSON {"categories": [3 short phrases, best first]}.'},
            {"role": "user", "content": f"Name: {name}\nAbout: {description}"},
        ], json_mode=True)
        found = json.loads(data["choices"][0]["message"].get("content") or "{}").get("categories", [])
        return [str(c).strip()[:80] for c in found if str(c).strip()][:3]
    except (LLMError, ValueError, KeyError, IndexError):
        log.warning("Category suggestion failed", exc_info=True)
        return []


@router.get("/site")
def site(url: str, current_user: User = Depends(get_current_user)):
    """What a website says about itself: name, description and suggested categories, to prefill setup."""
    target = url if "://" in url else f"https://{url}"
    got = safe_get(target)
    if not got or got[0] >= 400:
        return {"name": None, "description": None, "categories": []}
    page = got[1]
    title = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
    name = _meta(page, "og:site_name") or (re.split(r"\s[|\-–—:]\s", html.unescape(title.group(1)).strip())[0] if title else None)
    description = _meta(page, "og:description", "description")
    return {"name": name[:100] if name else None, "description": description[:300] if description else None, "categories": _categories(name, description)}
