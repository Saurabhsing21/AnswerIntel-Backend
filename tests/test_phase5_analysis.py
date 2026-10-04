import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.analysis.base import AnalysisContext
from app.analysis.citation import CitationAnalyzer
from app.analysis.competitor import CompetitorAnalyzer
from app.analysis.mention import BrandMentionAnalyzer
from app.analysis.models import Citation, CompetitorObservation, Mention
from app.analysis.persistence import save_analysis
from app.analysis.position import PositionAnalyzer
from app.analysis.recommendation import RecommendationAnalyzer
from app.analysis.sentiment import SentimentAnalyzer
from app.analysis.service import ResponseAnalysisService
from app.common.database import SessionLocal
from app.competitors.models import Competitor
from app.main import app
from app.projects.models import Project
from app.prompts.models import ScanPrompt
from app.providers.response_model import AIResponseRecord
from app.scans.models import Scan


client = TestClient(app)
API = "/api/v1"

BRAND = "Acme"
CONTEXT = AnalysisContext(
    brand_name=BRAND,
    competitors=[
        {"id": 1, "name": "Notion"},
        {"id": 2, "name": "ClickUp"},
    ],
)


def test_brand_mention_true():
    result = BrandMentionAnalyzer().analyze(
        "Acme is a great productivity tool.",
        CONTEXT,
    )
    assert result["mentioned"] is True


def test_brand_mention_false():
    result = BrandMentionAnalyzer().analyze(
        "Notion and ClickUp are popular.",
        CONTEXT,
    )
    assert result["mentioned"] is False


def test_recommendation_true():
    result = RecommendationAnalyzer().analyze(
        "Acme is a great choice for startups.",
        CONTEXT,
    )
    assert result["recommended"] is True


def test_mention_but_not_recommendation():
    text = "Acme is a company that provides productivity software."
    mention = BrandMentionAnalyzer().analyze(text, CONTEXT)
    recommendation = RecommendationAnalyzer().analyze(text, CONTEXT)
    assert mention["mentioned"] is True
    assert recommendation["recommended"] is False


def test_position_is_three():
    result = PositionAnalyzer().analyze(
        "1. Notion\n2. ClickUp\n3. Acme",
        CONTEXT,
    )
    assert result["position"] == 3


def test_competitors_mentioned():
    result = CompetitorAnalyzer().analyze(
        "Notion and ClickUp are good options.",
        CONTEXT,
    )
    by_name = {row["competitor_name"]: row["mentioned"] for row in result}
    assert by_name["Notion"] is True
    assert by_name["ClickUp"] is True


def test_sentiment_positive():
    result = SentimentAnalyzer().analyze(
        "Acme is an excellent choice.",
        CONTEXT,
    )
    assert result["sentiment"] == "positive"


def test_citation_url():
    result = CitationAnalyzer().analyze(
        "According to G2: https://g2.com/example",
        CONTEXT,
    )
    assert result[0]["url"] == "https://g2.com/example"


def test_phase5_complete_pipeline_persists_analysis():
    email = f"phase5-{uuid.uuid4().hex}@example.com"
    headers = {"Authorization": f"Bearer {_login(email)}"}

    project_id = client.post(
        f"{API}/projects",
        json={
            "brand_name": BRAND,
            "website": "https://example.com",
            "description": "A productivity platform for startups",
            "category": "productivity software",
            "country": "India",
        },
        headers=headers,
    ).json()["id"]

    for name, website in (
        ("Notion", "https://notion.so"),
        ("ClickUp", "https://clickup.com"),
    ):
        client.post(
            f"{API}/projects/{project_id}/competitors",
            json={"name": name, "website": website},
            headers=headers,
        )

    response_text = (
        "1. Notion\n"
        "2. ClickUp\n"
        "3. Acme\n\n"
        "Acme is a great choice for small startups.\n\n"
        "Source:\n"
        "https://www.g2.com/example"
    )

    with SessionLocal() as session:
        project = session.get(Project, uuid.UUID(project_id))
        competitors = session.scalars(
            select(Competitor).where(Competitor.project_id == project.id)
        ).all()
        competitor_ids = {row.name: row.id for row in competitors}

        scan = Scan(project_id=project.id, status="running")
        session.add(scan)
        session.flush()

        prompt = ScanPrompt(
            scan_id=scan.id,
            text="What are the best productivity tools?",
            category="CATEGORY",
            intent="DISCOVERY",
        )
        session.add(prompt)
        session.flush()

        record = AIResponseRecord(
            scan_id=scan.id,
            scan_prompt_id=prompt.id,
            provider="fake",
            model="test-model",
            prompt=prompt.text,
            response_text=response_text,
            raw_response={"fake": True},
        )
        session.add(record)
        session.flush()

        result = ResponseAnalysisService().analyze(
            response_text,
            AnalysisContext(
                brand_name=project.brand_name,
                competitors=[
                    {"id": row.id, "name": row.name}
                    for row in competitors
                ],
            ),
        )
        save_analysis(session, record.id, result)
        session.commit()

        mention = session.scalar(
            select(Mention).where(Mention.ai_response_id == record.id)
        )
        observations = session.scalars(
            select(CompetitorObservation).where(
                CompetitorObservation.ai_response_id == record.id
            )
        ).all()
        citations = session.scalars(
            select(Citation).where(Citation.ai_response_id == record.id)
        ).all()

        assert mention.brand_name == "Acme"
        assert mention.mentioned is True
        assert mention.recommended is True
        assert mention.position == 3
        assert mention.sentiment == "positive"

        by_id = {row.competitor_id: row.mentioned for row in observations}
        assert by_id[competitor_ids["Notion"]] is True
        assert by_id[competitor_ids["ClickUp"]] is True

        assert any(row.url == "https://www.g2.com/example" for row in citations)
        assert any(row.domain == "g2.com" for row in citations)


def _login(email: str) -> str:
    password = "password123"
    client.post(
        f"{API}/auth/register",
        json={"email": email, "password": password},
    )
    login = client.post(
        f"{API}/auth/login",
        json={"email": email, "password": password},
    )
    return login.json()["access_token"]
