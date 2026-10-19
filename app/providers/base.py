from dataclasses import dataclass, field


@dataclass
class ProviderContext:
    """What the scan is about. Real engines ignore it; the simulator uses it."""

    brand_name: str = ""
    competitors: list[str] = field(default_factory=list)
    brand_website: str = ""
    # Varies simulated answers between scans; real engines ignore it.
    variation: int = 0
    # Where the buyer is (the project's market): real answers and cited sources differ by country.
    country: str = ""
    # Search the web like the consumer app does, so answers match what people actually see.
    web_search: bool = False


@dataclass
class AIResponse:
    provider: str
    model: str
    prompt: str
    text: str
    raw_response: dict
    citations: list[str] = field(default_factory=list)
    latency_ms: int | None = None


class AIProvider:
    @property
    def name(self) -> str:
        raise NotImplementedError

    def ask(
        self,
        prompt: str,
        model: str,
        context: ProviderContext | None = None,
    ) -> AIResponse:
        raise NotImplementedError
