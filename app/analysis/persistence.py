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
    mention = result["mention"]
    recommendation = result["recommendation"]
    position = result["position"]
    sentiment = result["sentiment"]

    session.add(
        Mention(
            ai_response_id=ai_response_id,
            brand_name=mention["brand_name"],
            mentioned=mention["mentioned"],
            recommended=recommendation["recommended"],
            position=position["position"],
            sentiment=sentiment["sentiment"],
        )
    )

    for competitor in result["competitors"]:
        session.add(
            CompetitorObservation(
                ai_response_id=ai_response_id,
                competitor_id=competitor["competitor_id"],
                mentioned=competitor["mentioned"],
            )
        )

    for citation in result["citations"]:
        session.add(
            Citation(
                ai_response_id=ai_response_id,
                url=citation["url"],
                domain=citation.get("domain"),
            )
        )

    session.flush()
