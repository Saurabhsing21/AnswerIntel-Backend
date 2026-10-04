from app.analysis.base import ResponseAnalyzer


RECOMMENDATION_PATTERNS = (
    "great choice",
    "excellent choice",
    "good choice",
    "recommend",
    "recommended",
    "should choose",
    "best option",
    "best choice",
)


class RecommendationAnalyzer(ResponseAnalyzer):

    def analyze(self, response: str, context):
        text = response.lower()
        brand = context.brand_name.lower()

        if brand not in text:
            return {
                "recommended": False,
            }

        recommended = any(
            pattern in text
            for pattern in RECOMMENDATION_PATTERNS
        )

        return {
            "recommended": recommended,
        }
