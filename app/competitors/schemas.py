from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class CompetitorCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)  # trims stray spaces: "Grow " would read "Grow ?" in prompts

    name: str = Field(min_length=1, max_length=255)
    website: HttpUrl


class CompetitorUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)  # trims stray spaces: "Grow " would read "Grow ?" in prompts

    name: str | None = Field(default=None, min_length=1, max_length=255)
    website: HttpUrl | None = None
