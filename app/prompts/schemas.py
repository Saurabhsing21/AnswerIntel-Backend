from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.projects.schemas import check_engines

Category = Literal["CATEGORY", "COMPARISON", "ALTERNATIVE", "USE_CASE", "PROBLEM", "BUYER_INTENT", "COMPETITOR"]
Intent = Literal["DISCOVERY", "COMPARISON", "REPLACEMENT", "PURCHASE", "PROBLEM_SOLVING"]


class PromptCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)  # trims stray spaces: "Grow " would read "Grow ?" in prompts

    text: str = Field(min_length=8, max_length=300)
    category: Category = "CATEGORY"
    intent: Intent = "DISCOVERY"


class PromptUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)  # trims stray spaces: "Grow " would read "Grow ?" in prompts

    text: str | None = Field(default=None, min_length=8, max_length=300)
    category: Category | None = None
    intent: Intent | None = None
    is_active: bool | None = None
    # Engine keys; an empty list means "every engine the project scans".
    engines: list[str] | None = None

    @field_validator("engines")
    @classmethod
    def _engines(cls, keys: list[str] | None) -> list[str] | None:
        return None if keys is None else (check_engines(keys) if keys else [])


class PromptSuggest(BaseModel):
    instructions: str = Field(min_length=3, max_length=300)
    count: int = Field(default=10, ge=1, le=20)


class SuggestedPrompt(BaseModel):
    text: str = Field(min_length=8, max_length=300)
    category: Category
    intent: Intent
    importance: float | None = Field(default=None, ge=0, le=1)


class PromptsAccept(BaseModel):
    prompts: list[SuggestedPrompt] = Field(min_length=1, max_length=20)
