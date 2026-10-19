import logging

from app.analysis.base import AnalysisContext
from app.analysis.citation import CitationAnalyzer
from app.analysis.heuristic import analyze_name
from app.common.config import settings
from app.common.llm import LLMError

log = logging.getLogger(__name__)


class ResponseAnalysisService:
    def __init__(self, use_llm: bool | None = None):
        self.use_llm = settings.ai_enabled if use_llm is None else use_llm
        self.citation_analyzer = CitationAnalyzer()

    def analyze(
        self,
        response: str,
        context: AnalysisContext,
        citations: list[str] | None = None,
    ):
        method = "heuristic"
        brand = analyze_name(response, context.brand_name, context.aliases)
        competitors = {c["id"]: analyze_name(response, c["name"]) for c in context.competitors}

        if self.use_llm and response.strip():
            try:
                from app.analysis.llm import analyze_with_llm

                llm = analyze_with_llm(response, context)
                brand, competitors, method = llm["brand"], llm["competitors"], "llm"
            except LLMError as exc:
                log.warning("LLM analysis failed, using heuristics: %s", exc)

        return {
            "method": method,
            "mention": {
                "mentioned": brand["mentioned"],
                "brand_name": context.brand_name,
                "mention_count": brand.get("mention_count", 0),
            },
            "recommendation": {"recommended": brand["recommended"], "reason": brand.get("reason"), "evidence": brand.get("evidence")},
            "position": {"position": brand["position"]},
            "sentiment": {"sentiment": brand["sentiment"]},
            "competitors": [
                {
                    "competitor_id": c["id"],
                    "competitor_name": c["name"],
                    **{k: competitors[c["id"]][k] for k in ("mentioned", "recommended", "position", "sentiment")},
                    "reason": competitors[c["id"]].get("reason"),
                    "evidence": competitors[c["id"]].get("evidence"),
                }
                for c in context.competitors
            ],
            "citations": self.citation_analyzer.analyze(response, context, extra_urls=citations),
        }
