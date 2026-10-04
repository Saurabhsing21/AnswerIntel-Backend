from app.providers.models import ModelConfig, V1_MODELS


class ModelRegistry:

    def __init__(
        self,
        models: list[ModelConfig] | None = None,
    ):
        self.models = models or V1_MODELS

    def get_all(self) -> list[ModelConfig]:
        return self.models

    def get(self, key: str) -> ModelConfig:

        for model in self.models:
            if model.key == key:
                return model

        raise ValueError(f"Unknown model: {key}")