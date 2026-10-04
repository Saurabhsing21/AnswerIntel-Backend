from app.analysis.base import ResponseAnalyzer


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