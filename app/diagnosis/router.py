from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.analysis.models import Citation, CompetitorObservation, Mention
from app.auth.dependencies import get_current_user
from app.common.access import get_owned_project
from app.common.database import SessionLocal
from app.common.errors import AppError
from app.competitors.models import Competitor
from app.diagnosis.service import diagnose
from app.providers.response_model import AIResponseRecord
from app.scans.models import Scan
from app.users.models import User

router = APIRouter(prefix="/projects/{project_id}/responses", tags=["diagnosis"])


@router.get("/{response_id}/diagnosis")
def get_diagnosis(project_id: UUID, response_id: int, current_user: User = Depends(get_current_user)):
    """Why the brand is missing from this answer, with evidence and one action per cause."""
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        record = session.scalar(
            select(AIResponseRecord).join(Scan, Scan.id == AIResponseRecord.scan_id)
            .where(AIResponseRecord.id == response_id, Scan.project_id == project.id)
        )
        mention = session.scalar(select(Mention).where(Mention.ai_response_id == response_id))
        if not record or not mention:
            raise AppError(404, "RESPONSE_NOT_FOUND", "Answer not found.")
        names = {c.id: c.name for c in session.scalars(select(Competitor).where(Competitor.project_id == project.id))}
        competitors = [
            {"name": names[o.competitor_id], "mentioned": o.mentioned, "recommended": o.recommended,
             "reason": o.reason, "evidence": o.evidence}
            for o in session.scalars(select(CompetitorObservation).where(CompetitorObservation.ai_response_id == response_id))
            if o.competitor_id in names
        ]
        citations = [
            {"url": c.url, "domain": c.domain, "title": c.title, "is_brand_owned": c.is_brand_owned, "competitor_id": c.competitor_id}
            for c in session.scalars(select(Citation).where(Citation.ai_response_id == response_id))
        ]
        args = dict(
            brand=project.brand_name, website=project.website, engine=record.engine, prompt=record.prompt,
            mention={"mentioned": mention.mentioned, "recommended": mention.recommended,
                     "reason": mention.reason, "evidence": mention.evidence},
            competitors=competitors, citations=citations,
        )
    return diagnose(**args)  # page fetches run after the session is closed
