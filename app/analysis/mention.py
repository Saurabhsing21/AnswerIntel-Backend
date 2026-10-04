from app.analysis.base import ResponseAnalyzer
from app.analysis.heuristic import analyze_name


class BrandMentionAnalyzer(ResponseAnalyzer):
    def analyze(self, response: str, context):
        result = analyze_name(response, context.brand_name, context.aliases)
        return {
            "mentioned": result["mentioned"],
            "brand_name": context.brand_name,
            "mention_count": result["mention_count"],
        }
