from sqlalchemy.orm import Session

from app.analysis.models import (
    Mention,
    CompetitorObservation,
    Citation,
)


def save_analysis(
    session: Session,
    ai_response_id: int,
    result: dict,
):
    session.add(
        Mention(
            ai_response_id=ai_response_id,
            brand_name=result["mention"]["brand_name"],
            mentioned=result["mention"]["mentioned"],
            recommended=result["recommendation"]["recommended"],
            position=result["position"]["position"],
            sentiment=result["sentiment"]["sentiment"],
            reason=result["recommendation"].get("reason"),
            evidence=result["recommendation"].get("evidence"),
            analysis_method=result.get("method", "heuristic"),
        )
    )
    for competitor in result["competitors"]:
        session.add(
            CompetitorObservation(
                ai_response_id=ai_response_id,
                competitor_id=competitor["competitor_id"],
                mentioned=competitor["mentioned"],
                recommended=competitor.get("recommended", False),
                position=competitor.get("position"),
                sentiment=competitor.get("sentiment"),
                reason=(competitor.get("reason") or "")[:300] or None,
                evidence=competitor.get("evidence"),
            )
        )
    for citation in result["citations"]:
        session.add(
            Citation(
                ai_response_id=ai_response_id,
                url=citation["url"][:1000],
                domain=citation.get("domain"),
                source_type=citation.get("source_type"),
                is_brand_owned=citation.get("is_brand_owned", False),
                competitor_id=citation.get("competitor_id"),
            )
        )
    session.flush()
