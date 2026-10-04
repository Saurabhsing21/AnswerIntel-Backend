from dataclasses import dataclass, field


@dataclass
class ProviderContext:
    """What the scan is about. Real engines ignore it; the simulator uses it."""

    brand_name: str = ""
    competitors: list[str] = field(default_factory=list)
    brand_website: str = ""


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
