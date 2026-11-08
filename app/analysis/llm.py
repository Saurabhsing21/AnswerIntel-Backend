from typing import Literal

from pydantic import BaseModel, Field

from app.analysis.base import AnalysisContext
from app.analysis.heuristic import name_pattern
from app.common.config import settings
from app.common.llm import complete_json


class BrandVerdict(BaseModel):
    name: str = Field(max_length=200)
    mentioned: bool
    recommended: bool
    position: int | None = Field(default=None, ge=1, le=50)
    sentiment: Literal["positive", "neutral", "negative"] | None = None
    reason: str | None = Field(default=None, max_length=300)
    evidence: str | None = Field(default=None, max_length=600)


class AnalysisOutput(BaseModel):
    brands: list[BrandVerdict] = Field(max_length=120)  # the brand plus up to 100 competitors on Pro
    # Brands the answer recommends that are not in the list: the competitors the user is not tracking yet.
    other_brands: list[str] = Field(default_factory=list, max_length=30)


SYSTEM = """You analyze an AI assistant's answer to a buyer's question for a brand-visibility tool.
For EACH brand listed, decide:
- mentioned: the answer names the brand.
- recommended: the answer tells the reader to choose it, or presents it as one of its suggested picks.
  Every entry in a list of options, top picks or "other good options" counts as recommended, wherever it sits in the list,
  unless the answer advises against it there (e.g. "skip this", "not a fit").
  A passing or neutral mention is NOT a recommendation. If the answer says "X exists, but Y is recommended", only Y is recommended.
- position: its rank in an explicit numbered/ranked list, otherwise null. Never invent a ranking.
- sentiment: how the answer talks about that brand specifically (positive, neutral, negative), null if not mentioned.
- reason: one short phrase on why it was or was not recommended.
- evidence: the single sentence from the answer that best supports the verdict, copied word for word; null if not mentioned.
Also list in "other_brands" the names of other brands, companies or products the answer recommends that are NOT in the
list (empty list if none). Use the name as written in the answer; do not include generic terms or the listed brands.
Return JSON: {"brands": [{"name", "mentioned", "recommended", "position", "sentiment", "reason", "evidence"}], "other_brands": [...]}
covering exactly the listed brands in "brands"."""


def _own_names(name: str, aliases: list[str] | None) -> list[str]:
    """The name and its other names, without blanks or repeats (ignoring case)."""
    out: list[str] = []
    for n in [name, *(aliases or [])]:
        n = n.strip()
        if n and n.lower() not in {o.lower() for o in out}:
            out.append(n)
    return out


def analyze_with_llm(text: str, context: AnalysisContext) -> dict:
    # Each tracked brand with every name it goes by; a verdict under any of them is that brand's verdict.
    brand_names = _own_names(context.brand_name, context.aliases)
    competitor_names = {c["id"]: _own_names(c["name"], c.get("aliases")) for c in context.competitors}
    all_names = [*brand_names, *[n for names in competitor_names.values() for n in names]]
    # Only brands that appear get a verdict (verdict() discards the rest), so asking about the others only costs output tokens.
    present_names: list[str] = []
    for n in all_names:
        if name_pattern(n).search(text) and n.lower() not in {p.lower() for p in present_names}:
            present_names.append(n)
    user = (
        f"Question: {context.prompt}\n"
        f"Brands: {', '.join(present_names) or '(none of the tracked brands appear)'}\n\n"
        f"Answer:\n{text[:12000]}"
    )
    output = complete_json(settings.analysis_model, SYSTEM, user, AnalysisOutput)
    by_name = {v.name.strip().lower(): v for v in output.brands}

    def verdict(names: list[str]) -> dict:
        patterns = [name_pattern(n) for n in names]
        # Guard against hallucination: a brand none of whose names is in the text cannot be mentioned.
        present = any(p.search(text) for p in patterns)
        given = [v for n in names if (v := by_name.get(n.lower()))]
        claims = [v for v in given if v.mentioned] if present else []
        # If the model answered under two of its names, the recommending verdict wins.
        v = max(claims, key=lambda c: c.recommended) if claims else (given[0] if given else None)
        mentioned = bool(claims)
        return {
            "mentioned": mentioned,
            "recommended": bool(mentioned and v and v.recommended),
            "position": v.position if (mentioned and v) else None,
            "sentiment": (v.sentiment or "neutral") if (mentioned and v) else None,
            "reason": v.reason if v else None,
            # Only keep a quote that really is in the answer (LLM output is untrusted).
            "evidence": v.evidence.strip()[:400] if (mentioned and v and v.evidence and v.evidence.strip() in text) else None,
            # By where each mention starts, so "HubSpot CRM" counts once for "HubSpot" and "HubSpot CRM".
            "mention_count": len({m.start() for p in patterns for m in p.finditer(text)}),
        }

    listed = {n.lower() for n in all_names}
    # Untrusted output: keep only names that really appear in the answer and are not already tracked.
    others = []
    for raw in output.other_brands:
        name = raw.strip()[:100]
        if name and name.lower() not in listed and name.lower() not in {o.lower() for o in others} and name_pattern(name).search(text):
            others.append(name)
    return {
        "brand": verdict(brand_names),
        "competitors": {cid: verdict(names) for cid, names in competitor_names.items()},
        "other_brands": others,
    }
