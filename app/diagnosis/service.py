"""Why the brand is missing from one AI answer, and what to do about it.

Every cause carries evidence a user can check (a URL, a quoted sentence or a robots.txt rule); a cause
without evidence is never reported. Runs on demand, with no extra AI calls: only page fetches, capped and cached.
"""

import re
import time
from collections.abc import Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from app.common.safe_http import safe_get
from app.opportunities.site_audit import _visible_text

Fetch = Callable[[str], tuple[int, str] | None]

# The crawler each engine reads the web with.
ENGINE_AGENTS = {"chatgpt": "GPTBot", "perplexity": "PerplexityBot", "gemini": "Google-Extended", "google": "Googlebot"}
MAX_SOURCES = 6
MAX_SITEMAP_URLS = 200
CACHE_SECONDS = 24 * 3600
STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "to", "of", "in", "on", "with", "best", "top", "what", "which", "how",
    "is", "are", "my", "our", "your", "vs", "do", "i", "should", "use", "good", "tool", "tools", "software", "app",
    "apps", "2024", "2025", "2026", "that", "can", "me", "it", "most",
}
RANK = {"TECHNICAL": 0, "SOURCE_GAP": 1, "NO_ANSWER_PAGE": 2, "WINNING_CRITERIA": 3, "NOT_RECOMMENDED": 4}

_cache: dict[str, tuple[float, tuple[int, str] | None]] = {}


def cached_fetch(url: str) -> tuple[int, str] | None:
    hit = _cache.get(url)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    result = safe_get(url)
    _cache[url] = (time.monotonic(), result)
    return result


def _origin(url: str) -> str:
    parts = urlsplit(url if "://" in url else f"https://{url}")
    return f"{parts.scheme}://{parts.netloc}"


def _names_in(text: str, names: list[str]) -> list[str]:
    lower = text.lower()
    return [n for n in names if re.search(rf"(?<![a-z0-9]){re.escape(n.lower())}(?![a-z0-9])", lower)]


def _keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in STOPWORDS}


def technical(website: str, engine: str, fetch: Fetch) -> dict | None:
    agent = ENGINE_AGENTS.get(engine)
    robots = fetch(f"{_origin(website)}/robots.txt") if agent else None
    if not robots or robots[0] != 200:
        return None
    parser = RobotFileParser()
    parser.parse(robots[1].splitlines())
    if parser.can_fetch(agent, f"{_origin(website)}/"):
        return None
    return {
        "code": "TECHNICAL",
        "title": f"Your robots.txt blocks {agent}",
        "detail": f"{agent} is the crawler this engine reads the web with, so it cannot read your pages.",
        "action": f"Allow {agent} in robots.txt: add \"User-agent: {agent}\" followed by \"Allow: /\".",
        "evidence": {"url": f"{_origin(website)}/robots.txt", "agent": agent},
    }


def source_gap(brand: str, competitors: list[str], citations: list[dict], fetch: Fetch) -> dict | None:
    """Third-party pages the engine relied on that name competitors but not the brand."""
    pages, unread = [], []
    seen: set[str] = set()
    for c in citations:
        if c.get("is_brand_owned") or c.get("competitor_id") or not c.get("url") or c["url"] in seen:
            continue
        seen.add(c["url"])
        if len(seen) > MAX_SOURCES:
            break
        got = fetch(c["url"])
        if not got or got[0] >= 400:
            unread.append({"url": c["url"], "domain": c.get("domain")})
            continue
        text = _visible_text(got[1])
        if _names_in(text, [brand]):
            continue
        listed = _names_in(text, competitors)
        if listed:
            pages.append({"url": c["url"], "domain": c.get("domain"), "title": c.get("title"), "competitors": listed})
    if not pages:
        return None
    many = len(pages) > 1
    return {
        "code": "SOURCE_GAP",
        "title": f"{len(pages)} source{'s' if many else ''} behind this answer name{'' if many else 's'} competitors, not you",
        "detail": "The engine built this answer from these pages. They name your competitors and never name you.",
        "action": "Get onto these pages: ask the author to add you, submit a listing or review, or offer data they can quote.",
        "evidence": {"pages": pages, "unreadable": unread},
    }


def no_answer_page(website: str, prompt: str, citations: list[dict], fetch: Fetch) -> dict | None:
    """No page on the brand's site looks like it answers this question, judged from the sitemap URLs."""
    if any(c.get("is_brand_owned") for c in citations):
        return None
    sitemap = fetch(f"{_origin(website)}/sitemap.xml")
    if not sitemap or sitemap[0] != 200:
        return None
    urls = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sitemap[1])[:MAX_SITEMAP_URLS]
    words = _keywords(prompt)
    if not urls or not words:
        return None
    if max(len(words & _keywords(urlsplit(u).path.replace("-", " "))) for u in urls) >= 2:
        return None
    return {
        "code": "NO_ANSWER_PAGE",
        "title": "No page on your site answers this question",
        "detail": f"None of the {len(urls)} pages in your sitemap is about this question, and the engine cited none of your pages.",
        "action": "Publish a page that answers this exact question: a clear verdict near the top, a comparison table and sources.",
        "evidence": {"sitemap": f"{_origin(website)}/sitemap.xml", "pages_checked": len(urls), "keywords": sorted(words)},
    }


def winning_criteria(winners: list[dict], picked: bool = True) -> dict | None:
    quoted = [w for w in winners if w.get("evidence") or w.get("reason")]
    if not quoted:
        return None
    return {
        "code": "WINNING_CRITERIA",
        "title": f"{'Why the engine picked' if picked else 'What the answer says about'} {', '.join(w['name'] for w in quoted[:3])}",
        "detail": "These reasons come from the answer itself. If they are true for you too, your site and profiles should say so plainly.",
        "action": "State these points on your homepage, pricing and comparison pages, in words AI can quote.",
        "evidence": {"winners": [{"name": w["name"], "reason": w.get("reason"), "quote": w.get("evidence")} for w in quoted[:5]]},
    }


def diagnose(
    *, brand: str, website: str, engine: str, prompt: str, mention: dict, competitors: list[dict],
    citations: list[dict], fetch: Fetch | None = None,
) -> dict:
    """`mention`: the brand's verdict; `competitors`: [{name, mentioned, recommended, reason, evidence}]."""
    fetch = fetch or cached_fetch
    if mention.get("recommended"):
        return {"status": "recommended", "causes": []}
    picked = [c for c in competitors if c.get("recommended")]
    winners = picked or [c for c in competitors if c.get("mentioned")]  # nobody picked: what it said about the ones it named
    causes = [
        technical(website, engine, fetch),
        source_gap(brand, [c["name"] for c in competitors], citations, fetch),
        winning_criteria(winners, picked=bool(picked)),
    ]
    if mention.get("mentioned"):
        causes.append({
            "code": "NOT_RECOMMENDED",
            "title": "You are mentioned, but not recommended",
            "detail": "The engine knows you but did not pick you.",
            "action": "Give AI a case it can repeat: who you are best for, proof such as numbers and customers, and how you compare.",
            "evidence": {"quote": mention.get("evidence"), "reason": mention.get("reason")},
        })
    else:
        causes.append(no_answer_page(website, prompt, citations, fetch))
    found = sorted((c for c in causes if c), key=lambda c: RANK[c["code"]])
    return {"status": "mentioned" if mention.get("mentioned") else "absent", "causes": found}
