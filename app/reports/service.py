from datetime import date, timedelta

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.common.errors import AppError
from app.metrics.router import build_dashboard
from app.projects.models import Project
from app.reports.models import PERIOD_DAYS, Report


TITLES = {"weekly": "weekly AI visibility report", "monthly": "monthly AI visibility report", "manual": "AI visibility report"}


def report_title(report: Report) -> str:
    return f"{report.content['brand']}: {TITLES[report.type]}"


def _pct(value: float | None) -> str:
    return f"{round((value or 0) * 100)}%"


def _change(delta: float | None) -> str:
    if delta is None or round(delta * 100) == 0:
        return ""
    return f" ({'up' if delta > 0 else 'down'} {abs(round(delta * 100))} pts since the previous scan)"


def summarize(brand: str, visibility: dict, competitors: list[dict], opportunities: list[dict]) -> list[str]:
    deltas = visibility.get("deltas") or {}
    lines = [
        f"{brand} was mentioned in {_pct(visibility['mention_rate'])} of AI answers{_change(deltas.get('mention_rate'))}.",
        f"{brand} was recommended in {_pct(visibility['recommendation_rate'])} of AI answers"
        f"{_change(deltas.get('recommendation_rate'))}.",
    ]
    rivals = [c for c in competitors if not c["is_you"]]
    leader = max(rivals, key=lambda c: c["mention_rate"], default=None)
    if leader and leader["mention_rate"] > visibility["mention_rate"]:
        lines.append(f"{leader['name']} leads the field with a {_pct(leader['mention_rate'])} mention rate.")
    elif rivals:
        lines.append(f"{brand} leads every tracked competitor on mention rate.")
    if opportunities:
        top = opportunities[0]
        lines.append(f"Top opportunity: {top['title']}. {top['recommended_action']}")
    return lines


def build_content(session: Session, project: Project) -> tuple[dict, int]:
    data = build_dashboard(session, project)
    if not data["has_data"]:
        raise AppError(409, "NO_SCAN_DATA", "Run a scan first so the report has data.")
    opportunities = [
        {k: o[k] for k in ("type", "title", "description", "recommended_action", "impact")}
        for o in data["top_opportunities"]
    ]
    content = {
        "brand": project.brand_name,
        "website": project.website,
        "category": project.category,
        "visibility": data["visibility"],
        "engines": data["engines"],
        "competitors": data["competitors"],
        "top_opportunities": opportunities,
        "this_week": [
            {"title": o["title"], "steps": o["steps"][:3], "effort": o["effort"], "status": o["status"]}
            for o in data["this_week"]["items"]
        ],
        "trend": data["trend"],
        "summary": summarize(project.brand_name, data["visibility"], data["competitors"], opportunities),
    }
    return jsonable_encoder(content), data["metrics_scan"]["id"]


def create_report(session: Session, project: Project, report_type: str, today: date | None = None) -> Report:
    content, scan_id = build_content(session, project)
    end = today or date.today()
    report = Report(
        project_id=project.id,
        type=report_type,
        period_start=end - timedelta(days=PERIOD_DAYS[report_type]),
        period_end=end,
        scan_id=scan_id,
        content=content,
    )
    session.add(report)
    session.flush()
    return report
