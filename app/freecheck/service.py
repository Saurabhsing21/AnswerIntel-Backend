"""Run a free check: template prompts (no LLM cost), two engines, the normal answer analysis."""

import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

from app.analysis.base import AnalysisContext
from app.analysis.service import ResponseAnalysisService
from app.common.config import settings
from app.common.database import SessionLocal
from app.diagnosis import service as diagnosis
from app.freecheck.models import FreeCheck
from app.prompts.generator import PromptInput, TemplatePromptGenerator, generate_prompts
from app.providers.base import ProviderContext
from app.providers.registry import ModelRegistry, get_provider

log = logging.getLogger(__name__)


def pick_prompts(brand: str, category: str, country: str, count: int) -> list[str]:
    """Unbranded buyer questions: the ones that show whether AI finds you on its own."""
    candidates = generate_prompts(TemplatePromptGenerator(), PromptInput(brand, category, country, None, []))
    unbranded = [c["text"] for c in candidates if brand.lower() not in c["text"].lower()]
    return unbranded[:count]


def run_free_check(check_id: UUID) -> None:
    with SessionLocal() as session:
        check = session.get(FreeCheck, check_id)
        if not check or check.status != "queued":
            return
        check.status = "running"
        session.commit()
        brand, website, category, country = check.brand_name, check.website, check.category, check.country
    try:
        result = _check(brand, website, category, country)
        status = "done"
    except Exception:
        log.exception("Free check %s failed", check_id)
        result, status = None, "failed"
    with SessionLocal() as session:
        check = session.get(FreeCheck, check_id)
        check.status, check.result = status, result
        session.commit()


def _check(brand: str, website: str, category: str, country: str) -> dict:
    keys = {k.strip() for k in settings.free_check_engines.split(",") if k.strip()}
    engines = [e for e in ModelRegistry().get_all() if e.key in keys]
    prompts = pick_prompts(brand, category, country, settings.free_check_prompts)
    provider, analysis = get_provider(), ResponseAnalysisService()
    context = ProviderContext(brand_name=brand, brand_website=f"https://{website}", country=country)

    def ask(prompt: str, engine):
        from dataclasses import replace

        answer = provider.ask(prompt, engine.model, replace(context, web_search=engine.web_search))
        verdict = analysis.analyze(answer.text, AnalysisContext(brand_name=brand, competitors=[], brand_website=f"https://{website}", prompt=prompt), citations=answer.citations)
        return prompt, engine, verdict

    jobs = [(p, e) for p in prompts for e in engines]
    with ThreadPoolExecutor(max_workers=4) as pool:
        done = list(pool.map(lambda job: _safe(ask, *job), jobs))

    rows: dict[str, list[dict]] = {p: [] for p in prompts}
    sources: Counter = Counter()
    missed: list[tuple[str, list[dict]]] = []
    for item in done:
        if item is None:
            continue
        prompt, engine, v = item
        rows[prompt].append({
            "engine": engine.key, "engine_name": engine.display_name,
            "mentioned": v["mention"]["mentioned"], "recommended": v["recommendation"]["recommended"],
            "position": v["position"]["position"], "evidence": v["recommendation"].get("evidence"),
        })
        sources.update({c["domain"] for c in v["citations"] if c.get("domain")})
        if not v["mention"]["mentioned"]:
            missed.append((prompt, v["citations"]))
    answers = [a for row in rows.values() for a in row]
    return {
        "prompts": [{"text": p, "answers": rows[p]} for p in prompts],
        "summary": {
            "answers": len(answers),
            "mentioned": sum(a["mentioned"] for a in answers),
            "recommended": sum(a["recommended"] for a in answers),
            "engines": [e.display_name for e in engines],
        },
        "top_sources": [{"domain": d, "count": n} for d, n in sources.most_common(5)],
        "why": _safe(_why, website, [e.key for e in engines], missed) or [],
        "simulated": provider.name == "simulated",
    }


def _why(website: str, engines: list[str], missed: list[tuple[str, list[dict]]]) -> list[dict]:
    """The top reasons the brand was missed, from the same checks the app runs on each answer."""
    causes = {c["title"]: c for c in (diagnosis.technical(website, e, diagnosis.cached_fetch) for e in engines) if c}
    for prompt, citations in missed:
        page = diagnosis.no_answer_page(website, prompt, citations, diagnosis.cached_fetch)
        if page:
            causes[page["title"]] = {**page, "detail": f'Nothing on your site answers "{prompt}".'}
            break
    return list(causes.values())[:3]


def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception:
        log.warning("Free check answer failed", exc_info=True)
        return None
