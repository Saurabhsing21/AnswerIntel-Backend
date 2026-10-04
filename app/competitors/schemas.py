from pydantic import BaseModel, Field, HttpUrl


class CompetitorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    website: HttpUrl


class CompetitorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    website: HttpUrl | None = None
