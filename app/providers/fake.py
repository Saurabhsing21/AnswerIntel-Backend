from app.providers.base import AIProvider, AIResponse


class FakeAIProvider(AIProvider):

    @property
    def name(self) -> str:
        return "fake"

    def ask(
        self,
        prompt: str,
        model: str,
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