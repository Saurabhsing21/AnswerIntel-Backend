from collections import Counter
from datetime import date, datetime, timedelta, timezone

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.errors import AppError
from app.competitors.models import Competitor
from app.metrics.router import _engine_name, build_dashboard
from app.metrics.service import load_observations
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
        lines.append(f"{leader['name']} leads the field: AI mentions it in {_pct(leader['mention_rate'])} of answers.")
    elif rivals:
        lines.append(f"{brand} leads every tracked competitor on mention rate.")
    if opportunities:
        top = opportunities[0]
        lines.append(f"Top opportunity: {top['title']}. {top['recommended_action']}")
    return lines


def question_results(observations: list, names: dict[int, str]) -> list[dict]:
    """One row per question: how many engines named or picked the brand, and who they picked instead."""
    rows: dict[int, dict] = {}
    for o in observations:
        row = rows.setdefault(o.scan_prompt_id, {
            "text": o.prompt_text, "category": o.category, "engines": 0, "seen_on": 0, "recommended_on": 0, "winners": Counter(),
        })
        row["engines"] += 1
        row["seen_on"] += bool(o.brand["mentioned"])
        row["recommended_on"] += bool(o.brand["recommended"])
        row["winners"].update(names[cid] for cid, v in o.competitors.items() if v.get("recommended") and cid in names)
    out = []
    for row in rows.values():
        row["winners"] = [n for n, _ in row["winners"].most_common(3)]
        row["status"] = (
            "won" if row["recommended_on"] == row["engines"] else "shared" if row["recommended_on"]
            else "mentioned" if row["seen_on"] else "absent"
        )
        out.append(row)
    order = {"absent": 0, "mentioned": 1, "shared": 2, "won": 3}
    return sorted(out, key=lambda r: (order[r["status"]], -len(r["winners"])))


def top_sources(observations: list, brand: str, names: dict[int, str], limit: int = 10) -> list[dict]:
    """The sites AI cited most in this scan, and whose answers they backed."""
    agg: dict[str, dict] = {}
    for o in observations:
        for c in o.citations:
            if not c.get("domain"):
                continue
            row = agg.setdefault(c["domain"], {
                "domain": c["domain"], "citations": 0, "with_you": 0, "source_type": c.get("source_type"),
                "owner": brand if c.get("is_brand_owned") else names.get(c.get("competitor_id")),
            })
            row["citations"] += 1
            row["with_you"] += bool(o.brand["mentioned"])
    return sorted(agg.values(), key=lambda r: r["citations"], reverse=True)[:limit]


def build_content(session: Session, project: Project) -> tuple[dict, int]:
    data = build_dashboard(session, project)
    if not data["has_data"]:
        raise AppError(409, "NO_SCAN_DATA", "Run a scan first so the report has data.")
    opportunities = [
        {**{k: o[k] for k in ("type", "title", "description", "recommended_action", "impact")},
         "effort": o.get("effort"), "steps": (o.get("steps") or [])[:4]}
        for o in data["top_opportunities"]
    ]
    scan = data["metrics_scan"]
    observations = load_observations(session, scan["id"])
    names = {c.id: c.name for c in session.scalars(select(Competitor).where(Competitor.project_id == project.id))}
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
        "questions": question_results(observations, names),
        "sources": top_sources(observations, project.brand_name, names),
        "meta": {
            "generated_at": datetime.now(timezone.utc),
            "country": project.country,
            "scan_id": scan["id"],
            "scan_started_at": scan["started_at"],
            "scan_completed_at": scan["completed_at"],
            "engines": sorted({_engine_name(o.engine) for o in observations}),
            "questions": len({o.scan_prompt_id for o in observations}),
            "answers": len(observations),
            "failed_runs": scan["failed_runs"],
            "scans_in_trend": len(data["trend"]),
        },
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
