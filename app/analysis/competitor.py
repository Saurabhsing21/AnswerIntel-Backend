from app.analysis.base import ResponseAnalyzer
from app.analysis.heuristic import analyze_name


class CompetitorAnalyzer(ResponseAnalyzer):
    def analyze(self, response: str, context):
        results = []
        for competitor in context.competitors:
            verdict = analyze_name(response, competitor["name"])
            results.append({
                "competitor_id": competitor["id"],
                "competitor_name": competitor["name"],
                "mentioned": verdict["mentioned"],
                "recommended": verdict["recommended"],
                "position": verdict["position"],
                "sentiment": verdict["sentiment"],
            })
        return results
