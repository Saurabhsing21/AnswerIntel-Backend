from app.analysis.base import ResponseAnalyzer


POSITIVE_WORDS = (
    "excellent",
    "great",
    "good",
    "best",
    "amazing",
    "outstanding",
)

NEGATIVE_WORDS = (
    "bad",
    "poor",
    "worst",
    "terrible",
    "awful",
    "disappointing",
)


class SentimentAnalyzer(ResponseAnalyzer):

    def analyze(self, response: str, context):
        text = response.lower()
        brand = context.brand_name.lower()

        if brand not in text:
            return {
                "sentiment": None,
            }

        positive = sum(word in text for word in POSITIVE_WORDS)
        negative = sum(word in text for word in NEGATIVE_WORDS)

        if positive > negative:
            sentiment = "positive"
        elif negative > positive:
            sentiment = "negative"
        else:
            sentiment = "neutral"

        return {
            "sentiment": sentiment,
        }
