from app.analysis.base import ResponseAnalyzer


class BrandMentionAnalyzer(ResponseAnalyzer):

    def analyze(self, response: str, context):

        brand = context.brand_name.lower()
        text = response.lower()

        mentioned = brand in text

        return {
            "mentioned": mentioned,
            "brand_name": context.brand_name,
        }