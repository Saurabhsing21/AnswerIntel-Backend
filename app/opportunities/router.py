from typing import Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from sqlalchemy import func, select

from app.auth.dependencies import get_current_user
from app.billing.plans import entitlements, require_feature, require_pro
from app.experiments.models import Experiment
from app.experiments.router import _freeze as freeze_snapshot
from app.opportunities.retest import latest_full_scan, results_for
from app.prompts.models import Prompt
from app.scans.queue import enqueue_scan
from app.scans.service import ScanService
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
        # Carried across scans: what changed since last scan, when it first appeared, and the proof loop.
        "trend": o.trend, "first_seen_scan_id": o.first_seen_scan_id, "previous_count": o.evidence.get("previous_count"),
        "steps": o.evidence.get("steps") or [], "effort": o.evidence.get("effort"),
        "experiment_id": o.experiment_id, "retest": o.evidence.get("retest"), "locked": False,
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
        rows = sorted(session.scalars(query).all(), key=lambda o: (IMPACT_ORDER.get(o.impact, 9), -o.confidence))
        if entitlements(session, project.workspace_id).pro:
            return [serialize(o) for o in rows]
        # The free trial sees its top fixes in full; the rest show what kind of gap they are, not the fix.
        live = [o for o in rows if o.trend != "resolved"]
        visible = {o.id for o in live[:FREE_VISIBLE]}
        return [serialize(o) if o.id in visible or o.trend == "resolved" else locked(o) for o in rows]


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


FREE_VISIBLE = 3


def locked(o: Opportunity) -> dict:
    """An opportunity past the free trial's top 3: its kind and size, without the evidence or the fix."""
    return {
        **serialize(o), "title": "Upgrade to see this fix", "description": "", "recommended_action": "",
        "evidence": {}, "related_prompts": [], "steps": [], "expected_objective": None, "retest": None, "locked": True,
    }


def _owned(session, project, opportunity_id: int) -> Opportunity:
    opportunity = session.scalar(select(Opportunity).where(Opportunity.id == opportunity_id, Opportunity.project_id == project.id))
    if not opportunity:
        raise AppError(404, "OPPORTUNITY_NOT_FOUND", "Opportunity not found.")
    return opportunity


@router.post("/{opportunity_id}/experiment")
def track_as_experiment(project_id: UUID, opportunity_id: int, current_user: User = Depends(get_current_user)):
    """Start working on it and freeze today's numbers as the baseline, so the result can be proven later."""
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        ent = entitlements(session, project.workspace_id)
        require_pro(ent, "Tracked fixes")
        require_feature(ent, "experiments", "Experiments")
        opportunity = _owned(session, project, opportunity_id)
        if opportunity.experiment_id is None:
            baseline = session.scalar(
                select(MetricSnapshot).where(MetricSnapshot.project_id == project.id).order_by(MetricSnapshot.scan_id.desc())
            )
            if not baseline:
                raise AppError(409, "NO_BASELINE_SCAN", "Run a scan first so the experiment has a baseline.")
            experiment = Experiment(project_id=project.id, name=f"Fix: {opportunity.title}"[:255], description=opportunity.recommended_action)
            session.add(experiment)
            session.flush()
            session.add(freeze_snapshot(experiment.id, "baseline", baseline))
            opportunity.experiment_id = experiment.id
        opportunity.status = "in_progress"
        session.commit()
        session.refresh(opportunity)
        return serialize(opportunity)


@router.post("/{opportunity_id}/retest")
def retest(
    project_id: UUID, opportunity_id: int, background_tasks: BackgroundTasks, current_user: User = Depends(get_current_user)
):
    """Ask just this opportunity's prompts again now, and compare with the last full scan."""
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        require_pro(entitlements(session, project.workspace_id), "Re-tests")
        opportunity = _owned(session, project, opportunity_id)
        texts = [t.strip().lower() for t in opportunity.evidence.get("prompts") or []]
        prompt_ids = list(session.scalars(
            select(Prompt.id).where(Prompt.project_id == project.id, func.lower(Prompt.text).in_(texts))
        )) if texts else []
        if not prompt_ids:
            raise AppError(409, "NOTHING_TO_RETEST", "This opportunity isn't about specific prompts, so the next weekly scan will show the change.")
        before_scan = latest_full_scan(session, project.id)
        scan = ScanService().start_scan(session, project, prompt_ids=prompt_ids, opportunity_id=opportunity.id)
        opportunity.evidence = {**opportunity.evidence, "retest": {
            "status": "running", "scan_id": scan.id, "prompts": len(prompt_ids),
            "before": results_for(session, before_scan, texts) if before_scan else None,
        }}
        opportunity.status = "completed"
        session.commit()
        session.refresh(opportunity)
        enqueue_scan(scan.id, background_tasks)
        return serialize(opportunity)


@router.post("/{opportunity_id}/draft")
def draft_opportunity(project_id: UUID, opportunity_id: int, current_user: User = Depends(get_current_user)):
    """A first draft (page, FAQ, comparison or pitch) that carries out the recommended action. Not stored."""
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        require_pro(entitlements(session, project.workspace_id), "Drafts")  # calls the LLM
        opportunity = session.scalar(
            select(Opportunity).where(Opportunity.id == opportunity_id, Opportunity.project_id == project.id)
        )
        if not opportunity:
            raise AppError(404, "OPPORTUNITY_NOT_FOUND", "Opportunity not found.")
        return draft_for(project, opportunity)
