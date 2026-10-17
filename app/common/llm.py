import json
import time

import httpx
from pydantic import BaseModel, ValidationError

from app.common.config import settings


class LLMError(Exception):
    pass


def chat(
    model: str,
    messages: list[dict],
    *,
    json_mode: bool = False,
    timeout: float | None = None,
) -> dict:
    """One OpenRouter chat completion with retry on rate limits and server errors."""
    if not settings.ai_enabled:
        raise LLMError("OPENROUTER_API_KEY is not set")

    payload: dict = {"model": model, "messages": messages}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "HTTP-Referer": "https://seenlens.com",
        "X-Title": "SeenLens",
    }
    last_error: Exception | None = None
    for attempt in range(settings.provider_max_retries + 1):
        try:
            response = httpx.post(
                f"{settings.openrouter_base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=timeout or settings.provider_timeout_seconds,
            )
            if response.status_code in (429, 500, 502, 503, 504):
                raise LLMError(f"Provider returned {response.status_code}")
            if response.status_code >= 400:
                # Client errors (bad model, bad key) will not succeed on retry.
                raise LLMError(f"Provider rejected the request ({response.status_code})")
            data = response.json()
            if "choices" not in data or not data["choices"]:
                raise LLMError("Provider returned no choices")
            return data
        except (httpx.HTTPError, LLMError, ValueError) as exc:
            last_error = exc
            retryable = not (isinstance(exc, LLMError) and "rejected" in str(exc))
            if attempt < settings.provider_max_retries and retryable:
                time.sleep(2 * (attempt + 1))
                continue
            break
    raise LLMError(str(last_error) if last_error else "Provider call failed")


def complete_json[T: BaseModel](model: str, system: str, user: str, schema: type[T]) -> T:
    """Ask for JSON and validate it. LLM output is untrusted (PRD section 72)."""
    data = chat(
        model,
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        json_mode=True,
    )
    content = data["choices"][0]["message"].get("content") or ""
    content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return schema.model_validate(json.loads(content))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise LLMError(f"Invalid structured output: {exc.__class__.__name__}") from exc
