"""Re-test one opportunity: ask its prompts again and compare with the last full scan, so a fix shows its result."""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis.models import Mention
from app.metrics.models import MetricSnapshot
from app.opportunities.models import Opportunity
from app.prompts.models import ScanPrompt
from app.providers.response_model import AIResponseRecord
from app.scans.models import Scan


def results_for(session: Session, scan_id: int, texts: list[str]) -> dict:
    """How the brand did on these prompts in one scan: answers, mentions, recommendations."""
    wanted = [t.strip().lower() for t in texts]
    rows = session.execute(
        select(Mention.mentioned, Mention.recommended)
        .join(AIResponseRecord, AIResponseRecord.id == Mention.ai_response_id)
        .join(ScanPrompt, ScanPrompt.id == AIResponseRecord.scan_prompt_id)
        .where(AIResponseRecord.scan_id == scan_id, func.lower(ScanPrompt.text).in_(wanted))
    ).all()
    return {"answers": len(rows), "mentioned": sum(m for m, _ in rows), "recommended": sum(r for _, r in rows), "scan_id": scan_id}


def latest_full_scan(session: Session, project_id) -> int | None:
    return session.scalar(select(func.max(MetricSnapshot.scan_id)).where(MetricSnapshot.project_id == project_id))


def finish_retest(session: Session, scan: Scan) -> None:
    """Stores the re-test's result on its opportunity, next to the "before" taken when it started."""
    opportunity = session.get(Opportunity, scan.opportunity_id) if scan.opportunity_id else None
    if not opportunity:
        return
    texts = list(session.scalars(select(ScanPrompt.text).where(ScanPrompt.scan_id == scan.id)))
    retest = dict(opportunity.evidence.get("retest") or {})
    retest.update({
        "status": "done" if scan.completed_runs else "failed",
        "after": results_for(session, scan.id, texts),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    })
    opportunity.evidence = {**opportunity.evidence, "retest": retest}  # a new dict, so the JSON column is saved
