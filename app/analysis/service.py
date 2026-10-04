from app.analysis.base import AnalysisContext
from app.analysis.mention import BrandMentionAnalyzer
from app.analysis.recommendation import RecommendationAnalyzer
from app.analysis.position import PositionAnalyzer
from app.analysis.competitor import CompetitorAnalyzer
from app.analysis.sentiment import SentimentAnalyzer
from app.analysis.citation import CitationAnalyzer


class ResponseAnalysisService:

    def __init__(self):

        self.mention_analyzer = BrandMentionAnalyzer()
        self.recommendation_analyzer = RecommendationAnalyzer()
        self.position_analyzer = PositionAnalyzer()
        self.competitor_analyzer = CompetitorAnalyzer()
        self.sentiment_analyzer = SentimentAnalyzer()
        self.citation_analyzer = CitationAnalyzer()

    def analyze(
        self,
        response: str,
        context: AnalysisContext,
    ):

        mention = self.mention_analyzer.analyze(
            response,
            context,
        )

        recommendation = self.recommendation_analyzer.analyze(
            response,
            context,
        )

        position = self.position_analyzer.analyze(
            response,
            context,
        )

        competitors = self.competitor_analyzer.analyze(
            response,
            context,
        )

        sentiment = self.sentiment_analyzer.analyze(
            response,
            context,
        )

        citations = self.citation_analyzer.analyze(
            response,
            context,
        )

        return {
            "mention": mention,
            "recommendation": recommendation,
            "position": position,
            "competitors": competitors,
            "sentiment": sentiment,
            "citations": citations,
        }