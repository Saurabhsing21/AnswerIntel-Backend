from dataclasses import dataclass


@dataclass
class AnalysisContext:
    brand_name: str
    competitors: list[dict]


class ResponseAnalyzer:

    def analyze(
        self,
        response: str,
        context: AnalysisContext,
    ):
        raise NotImplementedError