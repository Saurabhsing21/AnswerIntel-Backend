import json
import time

import httpx
from pydantic import BaseModel, ValidationError

from app.common.config import settings
from app.costs.service import record_call


class LLMError(Exception):
    pass


class PermanentLLMError(LLMError):
    """The provider refused the request itself (bad key, unverified account, invalid input): retrying cannot help."""


def _record(model: str, response: httpx.Response, web_search: bool, started: float) -> None:
    """Ledger row for one attempt that got an HTTP response; the cost is whatever OpenRouter says it charged."""
    ok = response.status_code < 400
    data: dict = {}
    try:
        parsed = response.json()
        data = parsed if isinstance(parsed, dict) else {}
    except ValueError:
        pass
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
    record_call(
        provider="openrouter",
        model=model,
        usage=usage,
        generation_id=data.get("id"),
        cost_usd=(usage or {}).get("cost"),
        web_searches=1 if (web_search and ok) else 0,
        status="ok" if ok else "failed",
        latency_ms=int((time.monotonic() - started) * 1000),
    )


def chat(
    model: str,
    messages: list[dict],
    *,
    json_mode: bool = False,
    timeout: float | None = None,
    web_search: bool = False,
    retries: int | None = None,
) -> dict:
    """One OpenRouter chat completion with retry on rate limits and server errors (retries=None: the configured count)."""
    if not settings.ai_enabled:
        raise LLMError("OPENROUTER_API_KEY is not set")

    payload: dict = {"model": model, "messages": messages, "usage": {"include": True}}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if web_search:  # the model's own search (what the consumer app uses), billed per request by OpenRouter
        payload["plugins"] = [{"id": "web", "engine": "native"}]

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "HTTP-Referer": "https://seenlense.com",
        "X-Title": "Seenlense",
    }
    max_retries = settings.provider_max_retries if retries is None else retries
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        started = time.monotonic()
        try:
            response = httpx.post(
                f"{settings.openrouter_base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=timeout or settings.provider_timeout_seconds,
            )
            _record(model, response, web_search, started)
            if response.status_code in (429, 500, 502, 503, 504):
                raise LLMError(f"Provider returned {response.status_code}")
            if response.status_code >= 400:
                # Client errors (bad model, bad key) will not succeed on retry.
                raise PermanentLLMError(f"Provider rejected the request ({response.status_code})")
            data = response.json()
            if "choices" not in data or not data["choices"]:
                raise LLMError("Provider returned no choices")
            return data
        except (httpx.HTTPError, LLMError, ValueError) as exc:
            last_error = exc
            if isinstance(exc, httpx.HTTPError):  # no response came back, so nothing was billed
                record_call(
                    provider="openrouter", model=model, usage=None, generation_id=None, cost_usd=0,
                    web_searches=0, status="failed", latency_ms=int((time.monotonic() - started) * 1000),
                )
            retryable = not isinstance(exc, PermanentLLMError)
            if attempt < max_retries and retryable:
                time.sleep(2 * (attempt + 1))
                continue
            break
    if isinstance(last_error, PermanentLLMError):
        raise last_error
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
