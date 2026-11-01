"""The report as an email: the web report's hero numbers, key findings and first action, in the shared email layout.
Every value is escaped (brand and competitor names are user input)."""

import logging
from html import escape

from sqlalchemy.orm import Session

from app.common import storage
from app.common.config import settings
from app.common.email_layout import FAINT, INK, LINE, MUTED, email_html
from app.reports.document import score, score_label
from app.reports.models import Report, ReportPdf
from app.reports.service import report_title

log = logging.getLogger(__name__)


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{round(value * 100)}%"


def _cell(value: str, label: str, first: bool) -> str:
    rule = "" if first else f"border-left:1px solid {LINE};"
    return (
        f'<td width="25%" valign="top" class="rule" style="padding:2px 0 2px {0 if first else 12}px;{rule}">'
        f'<div class="ink" style="font-size:22px;line-height:1.1;font-weight:700;letter-spacing:-0.02em;color:{INK}">{escape(value)}</div>'
        f'<div class="muted" style="margin-top:4px;font-size:12px;color:{MUTED}">{escape(label)}</div></td>'
    )


def report_email_html(content: dict, report_url: str, pdf_attached: bool) -> str:
    v = content["visibility"]
    mention, recommend, cite = (v.get(k) or 0 for k in ("mention_rate", "recommendation_rate", "citation_rate"))
    points = score(mention, recommend, cite)
    hero = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:6px 0 22px"><tr>'
        f'<td class="ink" style="font-size:54px;line-height:1;font-weight:700;letter-spacing:-0.04em;color:{INK}">{points}'
        f'<span class="muted" style="font-size:18px;font-weight:600;color:{FAINT}"> / 100</span></td></tr>'
        f'<tr><td class="muted" style="padding-top:6px;font-size:13px;color:{MUTED}">AI visibility score (an estimate) · '
        f'<b>{escape(score_label(points))}</b></td></tr></table>'
    )
    numbers = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="rule" '
        f'style="margin:0 0 26px;border-top:1px solid {LINE};border-bottom:1px solid {LINE}"><tr><td style="padding:16px 0">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
        + "".join(_cell(_pct(v.get(key)), label, i == 0) for i, (label, key) in enumerate((
            ("Mentioned", "mention_rate"), ("Recommended", "recommendation_rate"),
            ("Share of voice", "share_of_voice"), ("Cited", "citation_rate"))))
        + "</tr></table></td></tr></table>"
    )
    findings = [line for line in content.get("summary") or [] if not line.startswith("Top opportunity:")]
    key_findings = ""
    if findings:
        key_findings = (
            f'<h2 class="ink" style="margin:0 0 10px;font-size:16px;color:{INK}">Key findings</h2>'
            f'<ul class="muted" style="margin:0 0 26px;padding-left:20px;font-size:14px;line-height:1.6;color:{MUTED}">'
            + "".join(f"<li style=\"margin-bottom:6px\">{escape(line)}</li>" for line in findings) + "</ul>"
        )
    first_move = ""
    opportunities = content.get("top_opportunities") or []
    if opportunities:
        top = opportunities[0]
        steps = "".join(f"<li style=\"margin-bottom:4px\">{escape(s)}</li>" for s in top.get("steps") or [])
        action = f'<p class="muted" style="margin:6px 0 0;font-size:14px;line-height:1.6;color:{MUTED}">{escape(top["recommended_action"])}</p>' if top.get("recommended_action") else ""
        first_move = (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="rule" style="margin:0 0 28px;border:1px solid {LINE};border-radius:12px">'
            f'<tr><td style="padding:16px 18px"><div class="muted" style="font-size:11px;font-weight:700;letter-spacing:0.08em;color:{FAINT}">DO THIS FIRST</div>'
            f'<div class="ink" style="margin-top:6px;font-size:16px;font-weight:700;color:{INK}">{escape(top["title"])}</div>{action}'
            + (f'<ol class="muted" style="margin:10px 0 0;padding-left:20px;font-size:13px;line-height:1.6;color:{MUTED}">{steps}</ol>' if steps else "")
            + "</td></tr></table>"
        )
    attach_note = "The full report is attached as a PDF. " if pdf_attached else ""
    title = f"{content['brand']} AI visibility report"
    return email_html(
        heading=title,
        paragraphs=[],
        blocks=hero + numbers + key_findings + first_move,
        button=("Open the full report", report_url),
        eyebrow=content["brand"],
        footer=f"{attach_note}The score is an estimate from the AI answers we collected in this scan.",
        preheader=f"AI visibility score {points}/100 for {content['brand']}.",
    )


def _pdf_bytes(session: Session, report_id: int) -> bytes | None:
    row = session.get(ReportPdf, report_id)
    if not row or row.status != "ready":
        return None
    if row.storage_key:
        try:
            return storage.get_pdf(row.storage_key)
        except Exception:
            log.exception("Could not read the PDF of report %s from storage", report_id)
            return None
    return row.pdf


def build_report_email(session: Session, report: Report) -> tuple[str, str, list[tuple[str, bytes]]]:
    """(subject, html, attachments). The PDF is attached only if it is ready; the link to the report is always there."""
    data = _pdf_bytes(session, report.id)
    url = f"{settings.app_base_url.rstrip('/')}/projects/{report.project_id}/reports/{report.id}"
    name = f"{report.content['brand']} AI Visibility Report {report.period_end:%Y-%m-%d}.pdf"
    safe = "".join(ch if ch.isalnum() or ch in " -." else "_" for ch in name)
    return report_title(report), report_email_html(report.content, url, data is not None), [(safe, data)] if data else []
