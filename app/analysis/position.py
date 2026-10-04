from app.analysis.base import ResponseAnalyzer
from app.analysis.heuristic import analyze_name


class PositionAnalyzer(ResponseAnalyzer):
    def analyze(self, response: str, context):
        # Only explicit ranked lists produce a position; prose stays None.
        return {
            "position": analyze_name(response, context.brand_name, context.aliases)["position"],
        }
