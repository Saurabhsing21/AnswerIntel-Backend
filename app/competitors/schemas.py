from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.common.aliases import check_aliases


class CompetitorCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)  # trims stray spaces: "Grow " would read "Grow ?" in prompts

    name: str = Field(min_length=1, max_length=255)
    website: HttpUrl
    aliases: list[str] | None = None  # other names: "HubSpot CRM" for "HubSpot"

    @field_validator("aliases")
    @classmethod
    def _aliases(cls, values: list[str] | None) -> list[str] | None:
        return check_aliases(values)


class CompetitorUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)  # trims stray spaces: "Grow " would read "Grow ?" in prompts

    name: str | None = Field(default=None, min_length=1, max_length=255)
    website: HttpUrl | None = None
    aliases: list[str] | None = None  # None keeps the current ones; [] clears them

    @field_validator("aliases")
    @classmethod
    def _aliases(cls, values: list[str] | None) -> list[str] | None:
        return check_aliases(values)
