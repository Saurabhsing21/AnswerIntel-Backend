"""Google AI Mode through DataForSEO's SERP API (Google has no public API for its AI answers).

One live request per prompt, about $0.004 each. The answer and its cited sources come back as an
`ai_overview` item; a query Google answers without AI returns no such item, which counts as an empty answer.
"""

import time

import httpx

from app.common.config import settings
from app.common.llm import LLMError
from app.providers.base import AIResponse, ProviderContext

URL = "https://api.dataforseo.com/v3/serp/google/ai_mode/live/advanced"

# DataForSEO wants full country names; projects often store ISO codes.
COUNTRIES = {
    "US": "United States", "USA": "United States", "UK": "United Kingdom", "GB": "United Kingdom", "IN": "India",
    "CA": "Canada", "AU": "Australia", "DE": "Germany", "FR": "France", "ES": "Spain", "IT": "Italy",
    "NL": "Netherlands", "BR": "Brazil", "MX": "Mexico", "SG": "Singapore", "AE": "United Arab Emirates",
    "IE": "Ireland", "NZ": "New Zealand", "ZA": "South Africa", "JP": "Japan",
}


def location_name(country: str) -> str:
    country = (country or "").strip()
    return COUNTRIES.get(country.upper(), country) or "United States"


def ask_google_ai(prompt: str, context: ProviderContext | None = None) -> AIResponse:
    if not settings.google_ai_enabled:
        raise LLMError("DataForSEO credentials are not set")
    started = time.monotonic()
    task = {"keyword": prompt[:700], "location_name": location_name(context.country if context else ""), "language_code": "en"}
    try:
        response = httpx.post(
            URL, json=[task], auth=(settings.dataforseo_login, settings.dataforseo_password),
            timeout=settings.provider_timeout_seconds,
        )
    except httpx.HTTPError as exc:
        raise LLMError(f"DataForSEO unreachable: {exc.__class__.__name__}") from exc
    if response.status_code >= 400:
        raise LLMError(f"DataForSEO returned {response.status_code}")
    data = response.json()
    task_result = (data.get("tasks") or [{}])[0]
    if task_result.get("status_code", 20000) >= 40000:
        raise LLMError(f"DataForSEO task failed: {task_result.get('status_message', 'unknown')}"[:200])
    items = ((task_result.get("result") or [{}])[0] or {}).get("items") or []
    overview = next((i for i in items if i.get("type") == "ai_overview"), {})
    references = overview.get("references") or []
    text = overview.get("markdown") or "\n".join(e.get("text") or "" for e in overview.get("items") or [])
    citations = list(dict.fromkeys(r["url"] for r in references if r.get("url")))
    return AIResponse(
        provider="dataforseo",
        model="google-ai-mode",
        prompt=prompt,
        text=text,
        raw_response={"cost": data.get("cost"), "ai_overview": overview},
        citations=citations,
        latency_ms=int((time.monotonic() - started) * 1000),
    )
