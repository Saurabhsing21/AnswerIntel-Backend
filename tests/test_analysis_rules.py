from app.analysis import llm as llm_module
from app.analysis.base import AnalysisContext
from app.analysis.citation import CitationAnalyzer
from app.analysis.heuristic import analyze_name
from app.analysis.llm import AnalysisOutput, BrandVerdict
from app.analysis.service import ResponseAnalysisService

CTX = AnalysisContext(
    brand_name="Acme",
    competitors=[{"id": 1, "name": "HubSpot", "website": "https://hubspot.com"}, {"id": 2, "name": "Attio"}],
    brand_website="https://acme.com",
)


def test_prd_example_mention_is_not_recommendation():
    # PRD section 26: the critical distinction.
    text = "Acme is a company that provides CRM software, but HubSpot is often recommended for startups."
    acme, hubspot = analyze_name(text, "Acme"), analyze_name(text, "HubSpot")
    assert acme["mentioned"] and not acme["recommended"]
    assert hubspot["mentioned"] and hubspot["recommended"]


def test_ranked_list_gives_position_and_recommendation():
    text = "1. HubSpot: popular.\n2. Attio: flexible.\n3. Acme: simple to start."
    assert analyze_name(text, "Acme")["position"] == 3
    assert analyze_name(text, "Acme")["recommended"] is True
    assert analyze_name(text, "HubSpot")["position"] == 1


def test_prose_never_invents_a_position():
    # PRD section 27: do not invent rankings.
    text = "Acme is one option, although HubSpot is generally better suited."
    assert analyze_name(text, "Acme")["position"] is None


def test_name_match_respects_word_boundaries():
    assert analyze_name("Acmeville is a town.", "Acme")["mentioned"] is False


def test_sentiment_is_scoped_to_the_brand():
    text = "HubSpot is excellent and powerful. Acme is limited and expensive."
    assert analyze_name(text, "Acme")["sentiment"] == "negative"
    assert analyze_name(text, "HubSpot")["sentiment"] == "positive"


def test_citations_are_classified_by_type_and_owner():
    urls = [
        "https://www.acme.com/pricing",
        "https://hubspot.com/compare",
        "https://www.g2.com/products/acme",
        "https://www.reddit.com/r/startups/x",
        "https://blog.example.com/best-crm",
    ]
    rows = {r["domain"]: r for r in CitationAnalyzer().analyze("", CTX, extra_urls=urls)}
    assert rows["acme.com"]["is_brand_owned"] and rows["acme.com"]["source_type"] == "brand_website"
    assert rows["hubspot.com"]["competitor_id"] == 1
    assert rows["g2.com"]["source_type"] == "review_site"
    assert rows["reddit.com"]["source_type"] == "reddit"
    assert rows["blog.example.com"]["source_type"] == "blog"


def test_llm_output_cannot_invent_a_mention(monkeypatch):
    # LLM output is untrusted (PRD section 72): a brand absent from the text stays unmentioned.
    def fake_complete_json(*_args, **_kwargs):
        return AnalysisOutput(brands=[
            BrandVerdict(name="Acme", mentioned=True, recommended=True, position=1, sentiment="positive"),
            BrandVerdict(name="HubSpot", mentioned=True, recommended=True, position=2, sentiment="positive"),
            BrandVerdict(name="Attio", mentioned=False, recommended=False),
        ])

    monkeypatch.setattr(llm_module, "complete_json", fake_complete_json)
    result = ResponseAnalysisService(use_llm=True).analyze("HubSpot is the best CRM for startups.", CTX)
    assert result["method"] == "llm"
    assert result["mention"]["mentioned"] is False
    assert result["recommendation"]["recommended"] is False
    hubspot = next(c for c in result["competitors"] if c["competitor_name"] == "HubSpot")
    assert hubspot["recommended"] is True


def test_llm_failure_falls_back_to_rules(monkeypatch):
    from app.common.llm import LLMError

    def boom(*_args, **_kwargs):
        raise LLMError("down")

    monkeypatch.setattr(llm_module, "complete_json", boom)
    result = ResponseAnalysisService(use_llm=True).analyze("I'd recommend Acme for small teams.", CTX)
    assert result["method"] == "heuristic"
    assert result["recommendation"]["recommended"] is True
