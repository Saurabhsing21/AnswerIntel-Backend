from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["CATEGORY", "COMPARISON", "ALTERNATIVE", "USE_CASE", "PROBLEM", "BUYER_INTENT", "COMPETITOR"]
Intent = Literal["DISCOVERY", "COMPARISON", "REPLACEMENT", "PURCHASE", "PROBLEM_SOLVING"]


class PromptCreate(BaseModel):
    text: str = Field(min_length=8, max_length=300)
    category: Category = "CATEGORY"
    intent: Intent = "DISCOVERY"


class PromptUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=8, max_length=300)
    category: Category | None = None
    intent: Intent | None = None
    is_active: bool | None = None
