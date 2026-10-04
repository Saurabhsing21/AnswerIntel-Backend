from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ScanResponse(BaseModel):
    id: int
    project_id: UUID
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
