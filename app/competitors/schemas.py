from pydantic import BaseModel, HttpUrl


class CompetitorCreate(BaseModel):
    name: str
    website: HttpUrl
