from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.common.access import get_owned_project
from app.common.database import SessionLocal
from app.common.errors import AppError
from app.experiments.models import Experiment, ExperimentSnapshot
from app.metrics.models import MetricSnapshot
from app.users.models import User

router = APIRouter(prefix="/projects/{project_id}/experiments", tags=["Experiments"])

METRICS = ("mention_rate", "recommendation_rate", "share_of_voice", "average_position")


class ExperimentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


def _snapshot(s: ExperimentSnapshot | None) -> dict | None:
    if not s:
        return None
    return {"scan_id": s.scan_id, "created_at": s.created_at, **{k: getattr(s, k) for k in METRICS}}


def _comparison(baseline: dict | None, after: dict | None) -> dict | None:
    if not baseline or not after:
        return None
    result = {}
    for key in METRICS:
        before, now = baseline[key], after[key]
        delta = round(now - before, 4) if before is not None and now is not None else None
        result[key] = {"before": before, "after": now, "delta": delta}
    return result


def serialize(session: Session, experiment: Experiment) -> dict:
    snapshots = {
        s.kind: s
        for s in session.scalars(select(ExperimentSnapshot).where(ExperimentSnapshot.experiment_id == experiment.id))
    }
    baseline, after = _snapshot(snapshots.get("baseline")), _snapshot(snapshots.get("after"))
    return {
        "id": experiment.id,
        "project_id": str(experiment.project_id),
        "name": experiment.name,
        "description": experiment.description,
        "status": experiment.status,
        "started_at": experiment.started_at,
        "ended_at": experiment.ended_at,
        "baseline": baseline,
        "after": after,
        "comparison": _comparison(baseline, after),
    }


def _get_experiment(session: Session, project_id: UUID, experiment_id: int, user_id: int) -> Experiment:
    project = get_owned_project(session, project_id, user_id)
    experiment = session.scalar(
        select(Experiment).where(Experiment.id == experiment_id, Experiment.project_id == project.id)
    )
    if not experiment:
        raise AppError(404, "EXPERIMENT_NOT_FOUND", "Experiment not found.")
    return experiment


def _latest_metrics(session: Session, project_id: UUID) -> MetricSnapshot | None:
    return session.scalar(
        select(MetricSnapshot).where(MetricSnapshot.project_id == project_id).order_by(MetricSnapshot.scan_id.desc())
    )


def _freeze(experiment_id: int, kind: str, metrics: MetricSnapshot) -> ExperimentSnapshot:
    return ExperimentSnapshot(
        experiment_id=experiment_id, scan_id=metrics.scan_id, kind=kind, **{k: getattr(metrics, k) for k in METRICS}
    )


@router.post("")
def create_experiment(project_id: UUID, payload: ExperimentCreate, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        baseline = _latest_metrics(session, project.id)
        if not baseline:
            raise AppError(409, "NO_BASELINE_SCAN", "Run a scan first so the experiment has a baseline.")
        experiment = Experiment(project_id=project.id, name=payload.name.strip(), description=payload.description)
        session.add(experiment)
        session.flush()
        session.add(_freeze(experiment.id, "baseline", baseline))
        session.commit()
        session.refresh(experiment)
        return serialize(session, experiment)


@router.get("")
def list_experiments(project_id: UUID, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        rows = session.scalars(
            select(Experiment).where(Experiment.project_id == project.id).order_by(Experiment.id.desc())
        ).all()
        return [serialize(session, e) for e in rows]


@router.get("/{experiment_id}")
def get_experiment(project_id: UUID, experiment_id: int, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        return serialize(session, _get_experiment(session, project_id, experiment_id, current_user.id))


@router.post("/{experiment_id}/complete")
def complete_experiment(project_id: UUID, experiment_id: int, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        experiment = _get_experiment(session, project_id, experiment_id, current_user.id)
        if experiment.status == "completed":
            raise AppError(409, "EXPERIMENT_ALREADY_COMPLETED", "This experiment is already completed.")
        baseline = session.scalar(
            select(ExperimentSnapshot).where(
                ExperimentSnapshot.experiment_id == experiment.id, ExperimentSnapshot.kind == "baseline"
            )
        )
        latest = _latest_metrics(session, experiment.project_id)
        if not latest or latest.scan_id <= baseline.scan_id:
            raise AppError(409, "NO_FOLLOWUP_SCAN", "Run a new scan after your change, then complete the experiment.")
        session.add(_freeze(experiment.id, "after", latest))
        experiment.status = "completed"
        experiment.ended_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(experiment)
        return serialize(session, experiment)
