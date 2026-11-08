from uuid import UUID

from pydantic import BaseModel, ConfigDict, HttpUrl, field_validator

from app.common.aliases import check_aliases
from app.providers.models import available_engines


class ProjectCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)  # trims stray spaces: "Grow " would read "Grow ?" in prompts

    brand_name: str
    website: HttpUrl
    description: str | None = None
    category: str
    country: str
    # Omitted = the user's personal workspace.
    workspace_id: UUID | None = None
    # Omitted = the default engines.
    engines: list[str] | None = None
    # Other names for the brand: "Halden CRM" for "Halden".
    aliases: list[str] | None = None

    @field_validator("engines")
    @classmethod
    def _engines(cls, keys: list[str] | None) -> list[str] | None:
        return check_engines(keys)

    @field_validator("aliases")
    @classmethod
    def _aliases(cls, values: list[str] | None) -> list[str] | None:
        return check_aliases(values)


class ProjectResponse(BaseModel):
    id: UUID
    brand_name: str
    website: str
    description: str | None
    category: str
    country: str



class ProjectUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)  # trims stray spaces: "Grow " would read "Grow ?" in prompts

    brand_name: str | None = None
    website: HttpUrl | None = None
    description: str | None = None
    category: str | None = None
    country: str | None = None
    engines: list[str] | None = None
    # Other names for the brand: "Halden CRM" for "Halden".
    aliases: list[str] | None = None

    @field_validator("engines")
    @classmethod
    def _engines(cls, keys: list[str] | None) -> list[str] | None:
        return check_engines(keys)

    @field_validator("aliases")
    @classmethod
    def _aliases(cls, values: list[str] | None) -> list[str] | None:
        return check_aliases(values)


def check_engines(keys: list[str] | None) -> list[str] | None:
    if keys is None:
        return None
    allowed = [e.key for e in available_engines()]
    unknown = sorted(set(keys) - set(allowed))
    if unknown:
        raise ValueError(f"Unknown or unavailable AI engines: {', '.join(unknown)}")
    if not keys:
        raise ValueError("Choose at least one AI engine.")
    return [k for k in allowed if k in keys]  # catalog order, no duplicates
