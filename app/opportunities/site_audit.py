"""Technical AI-readability audit (PRD 10, type 6): can AI crawlers reach and read the brand's website?"""

import re
from collections.abc import Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from app.common.safe_http import safe_get

AI_AGENTS = ("GPTBot", "ChatGPT-User", "PerplexityBot", "Google-Extended", "ClaudeBot", "CCBot")
CORE_AGENTS = {"GPTBot", "PerplexityBot", "Google-Extended"}
MIN_TEXT_CHARS = 300

_NON_CONTENT = re.compile(r"<(script|style|noscript)\b.*?</\1>", re.I | re.S)
_TAGS = re.compile(r"<[^>]+>")


def _visible_text(html: str) -> str:
    return re.sub(r"\s+", " ", _TAGS.sub(" ", _NON_CONTENT.sub(" ", html))).strip()


def audit_site(url: str, fetch: Callable[[str], tuple[int, str] | None] | None = None) -> dict | None:
    """Findings about the site, or None when it cannot be judged (unreachable, blocked, error page)."""
    fetch = fetch or (lambda target: safe_get(target))
    home = fetch(url)
    if not home or home[0] >= 400:
        return None  # unreachable is not evidence of a technical gap

    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    findings: list[dict] = []

    robots = fetch(f"{origin}/robots.txt")
    if robots and robots[0] == 200:
        parser = RobotFileParser()
        parser.parse(robots[1].splitlines())
        blocked = [agent for agent in AI_AGENTS if not parser.can_fetch(agent, f"{origin}/")]
        if blocked:
            findings.append({
                "code": "ROBOTS_BLOCKS_AI",
                "impact": "high" if CORE_AGENTS & set(blocked) else "medium",
                "agents": blocked,
                "message": f"robots.txt blocks AI crawlers: {', '.join(blocked)}.",
                "action": f"Update robots.txt to allow {', '.join(blocked)} to read your public pages.",
            })

    llms = fetch(f"{origin}/llms.txt")
    if not llms or llms[0] != 200 or not llms[1].strip():
        findings.append({
            "code": "NO_LLMS_TXT",
            "impact": "low",
            "message": "There is no llms.txt file summarising the site for AI.",
            "action": "Publish an llms.txt that describes what you do and links your key pages.",
        })

    if "application/ld+json" not in home[1].lower():
        findings.append({
            "code": "NO_STRUCTURED_DATA",
            "impact": "medium",
            "message": "The homepage has no JSON-LD structured data (Organization, Product, FAQ).",
            "action": "Add schema.org JSON-LD for your organization and products to the homepage.",
        })

    if len(_visible_text(home[1])) < MIN_TEXT_CHARS:
        findings.append({
            "code": "THIN_CONTENT",
            "impact": "medium",
            "message": "The homepage serves very little readable text, which suggests content that only appears after JavaScript runs.",
            "action": "Server-render the homepage so the key copy is present in the initial HTML.",
        })

    return {"url": url, "findings": findings}
