from dataclasses import dataclass


@dataclass(frozen=True)
class ModelConfig:
    key: str
    model: str
    display_name: str


V1_MODELS = [
    ModelConfig(
        key="model_1",
        model="YOUR_OPENROUTER_MODEL_SLUG_1",
        display_name="Model 1",
    ),
    ModelConfig(
        key="model_2",
        model="YOUR_OPENROUTER_MODEL_SLUG_2",
        display_name="Model 2",
    ),
    ModelConfig(
        key="model_3",
        model="YOUR_OPENROUTER_MODEL_SLUG_3",
        display_name="Model 3",
    ),
]