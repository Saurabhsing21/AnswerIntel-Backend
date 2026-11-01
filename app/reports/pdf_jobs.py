"""Report PDFs are drawn off the request path: by the `reports` Celery queue when Redis is configured, in-process
otherwise. Each report gets its PDF once, right after it is created, so a download is a database read."""

import json
import logging
import subprocess
import time
from pathlib import Path

from fastapi import BackgroundTasks

from app.common.config import settings
from app.common import storage
from app.common.database import SessionLocal
from app.reports.document import build_document
from app.reports.models import Report, ReportPdf

log = logging.getLogger(__name__)

RENDERER = Path(__file__).resolve().parents[2] / "pdf-renderer" / "dist" / "render.mjs"
FONTS = Path(__file__).parent / "fonts"


def render_pdf_bytes(document: dict) -> bytes:
    """Draws the document with the React PDF renderer (pdf-renderer/). About a second for a full report."""
    done = subprocess.run(
        ["node", str(RENDERER), str(FONTS)], input=json.dumps(document).encode(), capture_output=True, timeout=120,
    )
    if done.returncode != 0 or not done.stdout.startswith(b"%PDF"):
        raise RuntimeError(done.stderr.decode(errors="replace").strip()[-300:] or "The renderer returned no PDF")
    return done.stdout


def build_report_pdf(report_id: int, email_owner: bool = False) -> None:
    """Draws and stores one report's PDF. Safe to repeat: a redelivered job redraws the same file.
    `email_owner`: then emails the report (with the PDF if it rendered); emailed_at keeps that to once."""
    with SessionLocal() as session:
        report = session.get(Report, report_id)
        if not report:
            return
        row = session.get(ReportPdf, report_id) or ReportPdf(report_id=report_id, status="pending")
        session.add(row)
        started = time.monotonic()
        try:
            data = render_pdf_bytes(build_document(report.content))
            if settings.r2_enabled:
                key = f"reports/{report.project_id}/{report_id}.pdf"
                storage.put_pdf(key, data)
                row.storage_key, row.pdf = key, None
            else:
                row.storage_key, row.pdf = None, data
        except Exception as exc:
            log.exception("PDF for report %s failed", report_id)
            row.status, row.error = "failed", str(exc)[:300]
        else:
            row.status, row.error = "ready", None
            row.render_ms = round((time.monotonic() - started) * 1000)
        session.commit()
    if email_owner:
        from app.reports.delivery import email_report_to_owner  # delivery queues PDFs, so it imports this module

        email_report_to_owner(report_id)


def queue_report_pdf(report_id: int, background_tasks: BackgroundTasks | None = None, email_owner: bool = False) -> None:
    """Marks the PDF pending and hands it to the report worker. Without Redis it runs after the response
    (`background_tasks`) or, when already off the request path, right away."""
    with SessionLocal() as session:
        row = session.get(ReportPdf, report_id)
        if row:
            row.status, row.error = "pending", None
        else:
            session.add(ReportPdf(report_id=report_id, status="pending"))
        session.commit()
    if not settings.redis_url:
        if background_tasks is not None:
            background_tasks.add_task(build_report_pdf, report_id, email_owner)
        else:
            build_report_pdf(report_id, email_owner)
        return
    from app.worker.tasks import render_report_pdf_task

    try:
        render_report_pdf_task.delay(report_id, email_owner)
    except Exception:
        log.exception("Could not queue the PDF for report %s", report_id)
        with SessionLocal() as session:
            row = session.get(ReportPdf, report_id)
            row.status, row.error = "failed", "The job queue is unavailable."
            session.commit()
        if email_owner:
            from app.reports.delivery import email_report_to_owner

            email_report_to_owner(report_id)  # no worker will run: send the link-only email now
