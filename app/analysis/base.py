from dataclasses import dataclass, field


@dataclass
class AnalysisContext:
    brand_name: str
    # [{"id": int, "name": str, "website": str?}]
    competitors: list[dict]
    brand_website: str = ""
    prompt: str = ""
    aliases: list[str] = field(default_factory=list)


class ResponseAnalyzer:
    def analyze(
        self,
        response: str,
        context: AnalysisContext,
    ):
        raise NotImplementedError
