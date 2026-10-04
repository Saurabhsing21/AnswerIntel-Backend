from app.providers.base import AIProvider, AIResponse, ProviderContext


class FakeAIProvider(AIProvider):
    """Minimal echo provider for unit tests."""

    @property
    def name(self) -> str:
        return "fake"

    def ask(
        self,
        prompt: str,
        model: str,
        context: ProviderContext | None = None,
    ) -> AIResponse:
        text = f"Sample AI response for: {prompt}"
        return AIResponse(
            provider=self.name,
            model=model,
            prompt=prompt,
            text=text,
            raw_response={
                "fake": True,
                "prompt": prompt,
            },
        )
