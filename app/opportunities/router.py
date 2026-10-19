from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.billing.plans import entitlements, require_active
from app.common.access import get_owned_project
from app.common.database import SessionLocal
from app.common.errors import AppError
from app.metrics.models import MetricSnapshot
from app.opportunities.draft import draft_for
from app.opportunities.models import Opportunity
from app.opportunities.service import AREAS, IMPACT_ORDER
from app.users.models import User

router = APIRouter(prefix="/projects/{project_id}/opportunities", tags=["Opportunities"])


class OpportunityUpdate(BaseModel):
    status: Literal["open", "in_progress", "completed", "dismissed"]


def serialize(o: Opportunity) -> dict:
    return {
        "id": o.id, "scan_id": o.scan_id, "type": o.type, "title": o.title, "description": o.description,
        "recommended_action": o.recommended_action, "impact": o.impact, "confidence": o.confidence,
        "evidence": o.evidence, "status": o.status, "created_at": o.created_at, "updated_at": o.updated_at,
        # PRD 39: a recommendation states its objective and the prompts it relates to; PRD 11: grouped by area.
        "area": AREAS.get(o.type), "expected_objective": o.evidence.get("expected_objective"),
        "related_prompts": o.evidence.get("prompts") or [],
    }


@router.get("")
def list_opportunities(
    project_id: UUID,
    status: str | None = None,
    scan_id: int | None = None,
    current_user: User = Depends(get_current_user),
):
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        if scan_id is None:
            scan_id = session.scalar(
                select(MetricSnapshot.scan_id).where(MetricSnapshot.project_id == project.id).order_by(MetricSnapshot.scan_id.desc())
            )
        if scan_id is None:
            return []
        query = select(Opportunity).where(Opportunity.project_id == project.id, Opportunity.scan_id == scan_id)
        if status:
            query = query.where(Opportunity.status == status)
        rows = session.scalars(query).all()
        return [serialize(o) for o in sorted(rows, key=lambda o: (IMPACT_ORDER.get(o.impact, 9), -o.confidence))]


@router.get("/{opportunity_id}")
def get_opportunity(project_id: UUID, opportunity_id: int, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        opportunity = session.scalar(
            select(Opportunity).where(Opportunity.id == opportunity_id, Opportunity.project_id == project.id)
        )
        if not opportunity:
            raise AppError(404, "OPPORTUNITY_NOT_FOUND", "Opportunity not found.")
        return serialize(opportunity)


@router.patch("/{opportunity_id}")
def update_opportunity(
    project_id: UUID, opportunity_id: int, request: OpportunityUpdate, current_user: User = Depends(get_current_user)
):
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        opportunity = session.scalar(
            select(Opportunity).where(Opportunity.id == opportunity_id, Opportunity.project_id == project.id)
        )
        if not opportunity:
            raise AppError(404, "OPPORTUNITY_NOT_FOUND", "Opportunity not found.")
        opportunity.status = request.status
        session.commit()
        session.refresh(opportunity)
        return serialize(opportunity)


@router.post("/{opportunity_id}/draft")
def draft_opportunity(project_id: UUID, opportunity_id: int, current_user: User = Depends(get_current_user)):
    """A first draft (page, FAQ, comparison or pitch) that carries out the recommended action. Not stored."""
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        require_active(entitlements(session, project.workspace_id))  # calls the LLM
        opportunity = session.scalar(
            select(Opportunity).where(Opportunity.id == opportunity_id, Opportunity.project_id == project.id)
        )
        if not opportunity:
            raise AppError(404, "OPPORTUNITY_NOT_FOUND", "Opportunity not found.")
        return draft_for(project, opportunity)
