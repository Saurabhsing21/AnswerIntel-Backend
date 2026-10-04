from app.analysis.base import ResponseAnalyzer
from app.analysis.heuristic import RECOMMEND_CUES, analyze_name

RECOMMENDATION_PATTERNS = RECOMMEND_CUES


class RecommendationAnalyzer(ResponseAnalyzer):
    def analyze(self, response: str, context):
        result = analyze_name(response, context.brand_name, context.aliases)
        return {
            "recommended": result["recommended"],
        }
