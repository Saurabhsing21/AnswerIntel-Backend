from dataclasses import dataclass

from app.common.config import settings

GOOGLE_AI_MODEL = "dataforseo/google-ai-mode"


@dataclass(frozen=True)
class ModelConfig:
    key: str
    model: str
    display_name: str
    web_search: bool = False


# Every engine a project can scan, in the order the app shows them. Small models on purpose: each plan's monthly
# answer cap is priced for them (app/billing/plans.py). ENGINE_MODELS in the environment can swap a model.
CATALOG = (
    ModelConfig("chatgpt", "openai/gpt-5.4-nano", "ChatGPT"),
    ModelConfig("chatgpt_search", "openai/gpt-5.4-nano", "ChatGPT Search", web_search=True),
    ModelConfig("gemini", "google/gemini-3.1-flash-lite", "Gemini", web_search=True),
    ModelConfig("claude", "anthropic/claude-haiku-4.5", "Claude"),
    ModelConfig("grok", "x-ai/grok-4-fast", "Grok"),
    ModelConfig("llama", "meta-llama/llama-4-maverick", "Llama"),
    ModelConfig("mistral", "mistralai/mistral-small-3.2-24b-instruct", "Mistral AI"),
    ModelConfig("deepseek", "deepseek/deepseek-chat-v3.1", "DeepSeek"),
    ModelConfig("perplexity", "perplexity/sonar", "Perplexity"),  # always searches the web
    ModelConfig("qwen", "qwen/qwen3-235b-a22b-2507", "Qwen"),
    ModelConfig("google", GOOGLE_AI_MODEL, "Google AI Mode"),  # Google's own answer, through DataForSEO
)
# Shown in the app but not selectable: no public API to ask them through.
COMING_SOON = {"copilot": "Microsoft Copilot"}
# What a new project scans unless the user picks otherwise: the engines buyers use most, as they answer in their apps.
DEFAULT_ENGINES = ("chatgpt_search", "perplexity", "gemini", "google")

DISPLAY_NAMES = {e.key: e.display_name for e in CATALOG} | COMING_SOON


def _overrides() -> dict[str, str]:
    pairs = (part.split("=", 1) for part in settings.engine_models.split(",") if "=" in part)
    return {k.strip(): v.strip() for k, v in pairs if k.strip() and v.strip()}


def available_engines() -> list[ModelConfig]:
    """The catalog minus engines this deployment can't reach (Google AI Mode needs DataForSEO credentials)."""
    models = _overrides()
    return [
        ModelConfig(e.key, models.get(e.key, e.model), e.display_name, e.web_search)
        for e in CATALOG if e.key != "google" or settings.google_ai_enabled
    ]


def engines_for_project(selected: list[str] | None) -> list[ModelConfig]:
    """The engines a project scans: its own choice, or the defaults. Unknown or unreachable keys are skipped."""
    keys = set(selected) if selected else set(DEFAULT_ENGINES)
    return [e for e in available_engines() if e.key in keys]


V1_MODELS = engines_for_project(None)


def engines_for_prompt(engines: list[ModelConfig], selected: list[str] | None) -> list[ModelConfig]:
    """The project's engines a prompt runs on. A choice that no longer matches any of them falls back to all."""
    picked = [e for e in engines if selected and e.key in selected]
    return picked or engines
