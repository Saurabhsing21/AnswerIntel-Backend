from app.analysis.base import ResponseAnalyzer
from app.analysis.heuristic import NEGATIVE_WORDS, POSITIVE_WORDS, analyze_name

__all__ = ["SentimentAnalyzer", "POSITIVE_WORDS", "NEGATIVE_WORDS"]


class SentimentAnalyzer(ResponseAnalyzer):
    def analyze(self, response: str, context):
        # Scored only on sentences that mention the brand.
        return {
            "sentiment": analyze_name(response, context.brand_name, context.aliases)["sentiment"],
        }
