from openrouter import OpenRouter

from app.common.config import settings
from app.providers.base import AIProvider, AIResponse


class OpenRouterProvider(AIProvider):

    def __init__(self):
        self.client = OpenRouter(
            api_key=settings.openrouter_api_key,
        )

    @property
    def name(self) -> str:
        return "openrouter"

    def ask(
        self,
        prompt: str,
        model: str,
    ) -> AIResponse:

        response = self.client.chat.send(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        )

        text = response.choices[0].message.content or ""

        return AIResponse(
            provider=self.name,
            model=model,
            prompt=prompt,
            text=text,
            raw_response=response.model_dump(),
        )