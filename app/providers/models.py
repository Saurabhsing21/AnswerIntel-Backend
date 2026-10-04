from dataclasses import dataclass

from app.common.config import settings

DISPLAY_NAMES = {
    "chatgpt": "ChatGPT",
    "perplexity": "Perplexity",
    "gemini": "Gemini",
    "google": "Google AI",
    "claude": "Claude",
}


@dataclass(frozen=True)
class ModelConfig:
    key: str
    model: str
    display_name: str


def parse_engines(spec: str) -> list[ModelConfig]:
    engines: list[ModelConfig] = []
    for part in spec.split(","):
        if "=" not in part:
            continue
        key, model = (s.strip() for s in part.split("=", 1))
        if key and model:
            engines.append(ModelConfig(key=key, model=model, display_name=DISPLAY_NAMES.get(key, key.title())))
    return engines


V1_MODELS = parse_engines(settings.scan_engines)
