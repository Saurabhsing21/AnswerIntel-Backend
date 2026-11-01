from app.common.config import settings
from app.common.errors import ai_unavailable
from app.providers.base import AIProvider
from app.providers.models import ModelConfig, available_engines, engines_for_project


class ModelRegistry:
    def __init__(
        self,
        models: list[ModelConfig] | None = None,
    ):
        self.injected = models is not None  # tests pass their own engines and scan all of them
        self.models = models or available_engines()

    def get_all(self) -> list[ModelConfig]:
        return self.models

    def for_project(self, selected: list[str] | None) -> list[ModelConfig]:
        """The engines one project scans: its own choice, or the defaults."""
        return self.models if self.injected else engines_for_project(selected)

    def get(self, key: str) -> ModelConfig:
        for model in self.models:
            if model.key == key:
                return model
        raise ValueError(f"Unknown model: {key}")


def get_provider() -> AIProvider:
    """The real engines. Without a key there is nothing to fall back to: say so instead of inventing answers."""
    if not settings.ai_enabled:
        raise ai_unavailable()
    from app.providers.openrouter import OpenRouterProvider

    return OpenRouterProvider()
