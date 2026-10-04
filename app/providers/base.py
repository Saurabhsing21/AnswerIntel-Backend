from dataclasses import dataclass


@dataclass
class AIResponse:
    provider: str
    model: str
    prompt: str
    text: str
    raw_response: dict


class AIProvider:

    @property
    def name(self) -> str:
        raise NotImplementedError

    def ask(
        self,
        prompt: str,
        model: str,
    ) -> AIResponse:
        raise NotImplementedError