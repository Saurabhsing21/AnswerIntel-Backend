import time

from app.common.config import settings
from app.common.llm import chat
from app.providers.base import AIProvider, AIResponse, ProviderContext


def extract_citations(data: dict) -> list[str]:
    """Collect source URLs from the response (Perplexity-style and annotation-style)."""
    urls: list[str] = []
    for url in data.get("citations") or []:
        if isinstance(url, str):
            urls.append(url)
    message = (data.get("choices") or [{}])[0].get("message") or {}
    for annotation in message.get("annotations") or []:
        if annotation.get("type") == "url_citation":
            url = (annotation.get("url_citation") or {}).get("url")
            if url:
                urls.append(url)
    for result in data.get("search_results") or []:
        if isinstance(result, dict) and result.get("url"):
            urls.append(result["url"])
    seen: set[str] = set()
    return [u for u in urls if not (u in seen or seen.add(u))]


class OpenRouterProvider(AIProvider):
    @property
    def name(self) -> str:
        return "openrouter"

    def ask(
        self,
        prompt: str,
        model: str,
        context: ProviderContext | None = None,
    ) -> AIResponse:
        started = time.monotonic()
        data = chat(
            model,
            [{"role": "user", "content": prompt}],
            timeout=settings.provider_timeout_seconds,
        )
        text = data["choices"][0]["message"].get("content") or ""
        return AIResponse(
            provider=self.name,
            model=model,
            prompt=prompt,
            text=text,
            raw_response=data,
            citations=extract_citations(data),
            latency_ms=int((time.monotonic() - started) * 1000),
        )
