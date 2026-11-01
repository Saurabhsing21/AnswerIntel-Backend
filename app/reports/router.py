import secrets
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.billing.plans import entitlements, require_pro
from app.common import storage
from app.common.access import get_owned_project
from app.common.database import SessionLocal
from app.common.errors import AppError
from app.reports.email import send_report_email
from app.reports.document import score
from app.reports.models import Report, ReportPdf
from app.reports.pdf_jobs import queue_report_pdf
from app.reports.render import render_html
from app.reports.service import create_report, report_title
from app.users.models import User

router = APIRouter(prefix="/projects/{project_id}/reports", tags=["Reports"])
public_router = APIRouter(prefix="/shared/reports", tags=["Reports"])

class ReportCreate(BaseModel):
    type: Literal["weekly", "monthly", "manual"] = "weekly"


def serialize(report: Report, with_content: bool = True, pdf_status: str | None = None) -> dict:
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
        "pdf_status": pdf_status,
    }
    if with_content:
        data["content"] = report.content
    else:  # the list shows each report's numbers without sending every report's content
        v = report.content["visibility"]
        mention, recommend = v.get("mention_rate") or 0, v.get("recommendation_rate") or 0
        data["headline"] = {
            "mention_rate": mention, "recommendation_rate": recommend, "share_of_voice": v.get("share_of_voice") or 0,
            "score": score(mention, recommend, v.get("citation_rate") or 0),
        }
    return data


def _get_report(session: Session, project_id: UUID, report_id: int, user_id: int) -> Report:
    project = get_owned_project(session, project_id, user_id)
    report = session.scalar(select(Report).where(Report.id == report_id, Report.project_id == project.id))
    if not report:
        raise AppError(404, "REPORT_NOT_FOUND", "Report not found.")
    return report


def _pdf_statuses(session: Session, report_ids: list[int]) -> dict[int, str]:
    rows = session.execute(select(ReportPdf.report_id, ReportPdf.status).where(ReportPdf.report_id.in_(report_ids)))
    return dict(rows.all())


def _export(session: Session, report: Report, format: str, background_tasks: BackgroundTasks):
    if format == "html":
        # Defence in depth behind the HTML escaping: the page needs no scripts, frames, forms or remote loads.
        return Response(
            render_html(report.content, report_title(report)),
            media_type="text/html",
            headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"},
        )
    if format == "pdf":
        # Drawn by the report worker when the report was created; ask again (202) until it is ready.
        pdf = session.get(ReportPdf, report.id)
        if pdf and pdf.status == "ready":
            name = f"{report.content['brand']} AI Visibility Report {report.period_end:%Y-%m-%d}.pdf"
            safe = "".join(ch if ch.isalnum() or ch in " -." else "_" for ch in name)
            if pdf.storage_key:
                disposition = f'inline; filename="{safe}"'
                return RedirectResponse(storage.signed_url(pdf.storage_key, disposition=disposition), status_code=307)
            return Response(pdf.pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{safe}"'})
        if not pdf or pdf.status == "failed":  # reports from before the worker, or a failed render: try again
            queue_report_pdf(report.id, background_tasks)
        return JSONResponse({"status": "pending"}, status_code=202, headers={"Retry-After": "1"})
    return serialize(report, pdf_status=_pdf_statuses(session, [report.id]).get(report.id))


@router.post("")
def generate_report(
    project_id: UUID,
    background_tasks: BackgroundTasks,
    payload: ReportCreate | None = None,
    current_user: User = Depends(get_current_user),
):
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        require_pro(entitlements(session, project.workspace_id), "Reports")
        report = create_report(session, project, (payload or ReportCreate()).type)
        session.commit()
        session.refresh(report)
    queue_report_pdf(report.id, background_tasks)
    return serialize(report, pdf_status="pending")


@router.get("")
def list_reports(project_id: UUID, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        project = get_owned_project(session, project_id, current_user.id)
        rows = session.scalars(select(Report).where(Report.project_id == project.id).order_by(Report.id.desc())).all()
        statuses = _pdf_statuses(session, [r.id for r in rows])
        return [serialize(r, with_content=False, pdf_status=statuses.get(r.id)) for r in rows]


@router.get("/{report_id}")
def get_report(project_id: UUID, report_id: int, current_user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        report = _get_report(session, project_id, report_id, current_user.id)
        return serialize(report, pdf_status=_pdf_statuses(session, [report.id]).get(report.id))


@router.get("/{report_id}/export")
def export_report(
    project_id: UUID,
    report_id: int,
    background_tasks: BackgroundTasks,
    format: Literal["json", "html", "pdf"] = Query("json"),
    current_user: User = Depends(get_current_user),
):
    with SessionLocal() as session:
        return _export(session, _get_report(session, project_id, report_id, current_user.id), format, background_tasks)


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
def shared_report(token: str, background_tasks: BackgroundTasks, format: Literal["json", "html", "pdf"] = Query("json")):
    with SessionLocal() as session:
        report = session.scalar(select(Report).where(Report.share_token == token))
        if not report:
            raise AppError(404, "REPORT_NOT_FOUND", "This report link is invalid or has been revoked.")
        return _export(session, report, format, background_tasks)
