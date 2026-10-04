from app.analysis.base import ResponseAnalyzer


class CompetitorAnalyzer(ResponseAnalyzer):

    def analyze(self, response: str, context):

        text = response.lower()

        results = []

        for competitor in context.competitors:

            mentioned = (
                competitor["name"].lower() in text
            )

            results.append({
                "competitor_id": competitor["id"],
                "competitor_name": competitor["name"],
                "mentioned": mentioned,
            })

        return results