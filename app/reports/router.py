import secrets
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.common.access import get_owned_project
from app.common.database import SessionLocal
from app.common.errors import AppError
from app.reports.email import send_report_email
from app.reports.models import Report
from app.reports.render import render_html, render_pdf
from app.reports.service import create_report, report_title
from app.users.models import User

router = APIRouter(prefix="/projects/{project_id}/reports", tags=["Reports"])
public_router = APIRouter(prefix="/shared/reports", tags=["Reports"])

class ReportCreate(BaseModel):
    type: Literal["weekly", "monthly", "manual"] = "weekly"


def serialize(report: Report, with_content: bool = True) -> dict:
    data = {
        "id": report.id,
        "type": report.type,
        "status": report.status,
        "period_start": report.period_start,
        "period_end": report.period_end,
        "scan_id": report.scan_id,
        "created_at": report.created_at,
        "emailed_at": report.emailed_at,
        "shared": report.share_token is not None,
    }
    if with_content:
        data["content"] = report.content
    return data


def _get_report(session: Session, project_id: UUID, report_id: int, user_id: int) -> Report:
    project = get_owned_project(session, project_id, user_id)
    report = session.scalar(select(Report).where(Report.id == report_id, Report.project_id == project.id))
    if not report:
        raise AppError(404, "REPORT_NOT_FOUND", "Report not found.")
    return report


def _export(report: Report, format: str):
    if format == "html":
        # Defence in depth behind the HTML escaping: the page needs no scripts, frames, forms or remote loads.
        return Response(
            render_html(report.content, report_title(report)),
            media_type="text/html",
            headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"},
        )
    if format == "pdf":
        return Response(render_pdf(report.content, report_title(report)), media_type="application/pdf")
    return serialize(report)


@router.post("")
def generate_report(project_id: UUID, payload: ReportCreate | None = None, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        report = create_report(session, project, (payload or ReportCreate()).type)
        session.commit()
        session.refresh(report)
        return serialize(report)


@router.get("")
def list_reports(project_id: UUID, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        rows = session.scalars(select(Report).where(Report.project_id == project.id).order_by(Report.id.desc())).all()
        return [serialize(r, with_content=False) for r in rows]


@router.get("/{report_id}")
def get_report(project_id: UUID, report_id: int, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        return serialize(_get_report(session, project_id, report_id, current_user.id))


@router.get("/{report_id}/export")
def export_report(
    project_id: UUID,
    report_id: int,
    format: Literal["json", "html", "pdf"] = Query("json"),
    current_user: User = Depends(get_current_user),
):
    with SessionLocal() as session:
        return _export(_get_report(session, project_id, report_id, current_user.id), format)


@router.post("/{report_id}/share")
def share_report(project_id: UUID, report_id: int, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        report = _get_report(session, project_id, report_id, current_user.id)
        if not report.share_token:
            report.share_token = secrets.token_urlsafe(24)
            session.commit()
        return {"token": report.share_token}


@router.delete("/{report_id}/share")
def revoke_share(project_id: UUID, report_id: int, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        report = _get_report(session, project_id, report_id, current_user.id)
        report.share_token = None
        session.commit()
        return {"shared": False}


@router.post("/{report_id}/send")
def email_report(project_id: UUID, report_id: int, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        report = _get_report(session, project_id, report_id, current_user.id)
        send_report_email(current_user.email, report_title(report), render_html(report.content, report_title(report)))
        report.emailed_at = datetime.now(timezone.utc)
        session.commit()
        return {"sent": True, "to": current_user.email}


@public_router.get("/{token}")
def shared_report(token: str, format: Literal["json", "html", "pdf"] = Query("json")):
    with SessionLocal() as session:
        report = session.scalar(select(Report).where(Report.share_token == token))
        if not report:
            raise AppError(404, "REPORT_NOT_FOUND", "This report link is invalid or has been revoked.")
        return _export(report, format)
