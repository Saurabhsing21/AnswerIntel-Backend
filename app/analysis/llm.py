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


class AnalysisOutput(BaseModel):
    brands: list[BrandVerdict] = Field(max_length=30)


SYSTEM = """You analyze an AI assistant's answer to a buyer's question for a brand-visibility tool.
For EACH brand listed, decide:
- mentioned: the answer names the brand.
- recommended: the answer tells the reader to choose it, or presents it as one of its suggested picks.
  A passing or neutral mention is NOT a recommendation. If the answer says "X exists, but Y is recommended", only Y is recommended.
- position: its rank in an explicit numbered/ranked list, otherwise null. Never invent a ranking.
- sentiment: how the answer talks about that brand specifically (positive, neutral, negative), null if not mentioned.
- reason: one short phrase on why it was or was not recommended.
Return JSON: {"brands": [{"name", "mentioned", "recommended", "position", "sentiment", "reason"}]} covering exactly the listed brands."""


def analyze_with_llm(text: str, context: AnalysisContext) -> dict:
    names = [context.brand_name, *[c["name"] for c in context.competitors]]
    user = (
        f"Question: {context.prompt}\n"
        f"Brands: {', '.join(names)}\n\n"
        f"Answer:\n{text[:12000]}"
    )
    output = complete_json(settings.analysis_model, SYSTEM, user, AnalysisOutput)
    by_name = {v.name.strip().lower(): v for v in output.brands}

    def verdict(name: str) -> dict:
        v = by_name.get(name.lower())
        present = bool(name_pattern(name).search(text))
        # Guard against hallucination: a brand absent from the text cannot be mentioned.
        mentioned = bool(v and v.mentioned and present)
        return {
            "mentioned": mentioned,
            "recommended": bool(mentioned and v and v.recommended),
            "position": v.position if (mentioned and v) else None,
            "sentiment": (v.sentiment or "neutral") if (mentioned and v) else None,
            "reason": v.reason if v else None,
            "mention_count": len(name_pattern(name).findall(text)),
        }

    return {"brand": verdict(context.brand_name), "competitors": {c["id"]: verdict(c["name"]) for c in context.competitors}}
