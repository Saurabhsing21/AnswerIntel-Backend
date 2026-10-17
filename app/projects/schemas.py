from uuid import UUID

from pydantic import BaseModel, HttpUrl


class ProjectCreate(BaseModel):
    brand_name: str
    website: HttpUrl
    description: str | None = None
    category: str
    country: str
    # Omitted = the user's personal workspace.
    workspace_id: UUID | None = None


class ProjectResponse(BaseModel):
    id: UUID
    brand_name: str
    website: str
    description: str | None
    category: str
    country: str



class ProjectUpdate(BaseModel):
    brand_name: str | None = None
    website: HttpUrl | None = None
    description: str | None = None
    category: str | None = None
    country: str | None = None