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


def _capture_llm(monkeypatch, output):
    sent = {}

    def fake_complete_json(_model, _system, user, _schema):
        sent["user"] = user
        return output

    monkeypatch.setattr(llm_module, "complete_json", fake_complete_json)
    return sent


def test_llm_prompt_lists_only_brands_found_in_the_answer(monkeypatch):
    sent = _capture_llm(monkeypatch, AnalysisOutput(brands=[
        BrandVerdict(name="HubSpot", mentioned=True, recommended=True, position=1, sentiment="positive"),
    ]))
    result = llm_module.analyze_with_llm("HubSpot is the best CRM for startups.", CTX)
    brands_line = next(line for line in sent["user"].splitlines() if line.startswith("Brands:"))
    assert brands_line == "Brands: HubSpot"
    # The competitor that was left out of the prompt still gets a not-mentioned verdict.
    attio = result["competitors"][2]
    assert attio["mentioned"] is False and attio["recommended"] is False and attio["mention_count"] == 0
    assert result["competitors"][1]["recommended"] is True


def test_llm_prompt_includes_aliases_found_in_the_answer(monkeypatch):
    ctx = AnalysisContext(brand_name="Acme", aliases=["Acme CRM", "Acme Cloud"], competitors=[], prompt="Best CRM?")
    sent = _capture_llm(monkeypatch, AnalysisOutput(brands=[]))
    llm_module.analyze_with_llm("Try Acme CRM today.", ctx)
    assert "Brands: Acme, Acme CRM\n" in sent["user"]


def test_llm_call_is_still_made_when_no_tracked_brand_appears(monkeypatch):
    sent = _capture_llm(monkeypatch, AnalysisOutput(brands=[], other_brands=["Pipedrive", "Zoho"]))
    result = llm_module.analyze_with_llm("Pipedrive and Zoho are good picks.", CTX)
    assert "Brands: (none of the tracked brands appear)" in sent["user"]
    assert result["other_brands"] == ["Pipedrive", "Zoho"]
    assert result["brand"]["mentioned"] is False


# --- Other names (aliases) for the brand and competitors ---

HUBSPOT_ALIAS_CTX = AnalysisContext(
    brand_name="Acme",
    aliases=["Acme CRM"],
    competitors=[{"id": 1, "name": "HubSpot", "aliases": ["HubSpot CRM"]}, {"id": 2, "name": "Attio"}],
    prompt="Best CRM?",
)


def test_competitor_alias_matches_the_competitor():
    # "HubSpot CRM" must count for the competitor named "HubSpot" even if the plain name is absent.
    text = "I recommend HubSpot CRM for startups."
    assert analyze_name(text, "HubSpot", ["HubSpot CRM"])["mentioned"] is True
    result = ResponseAnalysisService(use_llm=False).analyze("Our top pick is Zoho Hub, then HubSpot CRM.", HUBSPOT_ALIAS_CTX)
    hubspot = next(c for c in result["competitors"] if c["competitor_name"] == "HubSpot")
    assert hubspot["mentioned"] is True
    attio = next(c for c in result["competitors"] if c["competitor_name"] == "Attio")
    assert attio["mentioned"] is False


def test_name_and_alias_in_one_phrase_count_once():
    # "HubSpot CRM" matches both patterns at the same spot: that is one mention, not two.
    assert analyze_name("Try HubSpot CRM today.", "HubSpot", ["HubSpot CRM"])["mention_count"] == 1
    assert analyze_name("HubSpot is fine. HubSpot CRM is better.", "HubSpot", ["HubSpot CRM"])["mention_count"] == 2


def test_llm_brand_named_only_by_its_alias_is_mentioned(monkeypatch):
    # The model answers under the alias it was shown; that verdict belongs to the brand.
    _capture_llm(monkeypatch, AnalysisOutput(brands=[
        BrandVerdict(name="Acme CRM", mentioned=True, recommended=True, position=1, sentiment="positive", reason="best"),
    ]))
    result = llm_module.analyze_with_llm("1. Acme CRM is the best choice for small teams.", HUBSPOT_ALIAS_CTX)
    brand = result["brand"]
    assert brand["mentioned"] is True and brand["recommended"] is True and brand["position"] == 1
    assert brand["mention_count"] == 1


def test_llm_verdict_under_the_main_name_counts_when_only_the_alias_is_in_the_text(monkeypatch):
    _capture_llm(monkeypatch, AnalysisOutput(brands=[BrandVerdict(name="Acme", mentioned=True, recommended=False)]))
    result = llm_module.analyze_with_llm("People like Acme CRM.", HUBSPOT_ALIAS_CTX)
    assert result["brand"]["mentioned"] is True


def test_llm_competitor_verdict_under_its_alias_counts(monkeypatch):
    _capture_llm(monkeypatch, AnalysisOutput(brands=[
        BrandVerdict(name="HubSpot CRM", mentioned=True, recommended=True, position=2, sentiment="positive"),
    ]))
    result = llm_module.analyze_with_llm("1. Zoho\n2. HubSpot CRM", HUBSPOT_ALIAS_CTX)
    hubspot = result["competitors"][1]
    assert hubspot["mentioned"] is True and hubspot["recommended"] is True and hubspot["position"] == 2


def test_llm_prefers_the_recommending_verdict_when_both_names_get_one(monkeypatch):
    _capture_llm(monkeypatch, AnalysisOutput(brands=[
        BrandVerdict(name="Acme", mentioned=True, recommended=False),
        BrandVerdict(name="Acme CRM", mentioned=True, recommended=True, position=1),
    ]))
    result = llm_module.analyze_with_llm("1. Acme CRM is the best choice.", HUBSPOT_ALIAS_CTX)
    assert result["brand"]["recommended"] is True and result["brand"]["position"] == 1


def test_llm_alias_absent_from_the_text_cannot_be_invented(monkeypatch):
    _capture_llm(monkeypatch, AnalysisOutput(brands=[
        BrandVerdict(name="Acme CRM", mentioned=True, recommended=True),
        BrandVerdict(name="HubSpot CRM", mentioned=True, recommended=True),
    ]))
    result = llm_module.analyze_with_llm("Pipedrive is a solid pick.", HUBSPOT_ALIAS_CTX)
    assert result["brand"]["mentioned"] is False
    assert result["competitors"][1]["mentioned"] is False


def test_llm_prompt_skips_empty_and_repeated_names(monkeypatch):
    ctx = AnalysisContext(
        brand_name="Acme", aliases=["", "acme", "Acme CRM", "HubSpot"],
        competitors=[{"id": 1, "name": "HubSpot", "aliases": ["", "Hub Spot", "hubspot"]}], prompt="Best CRM?",
    )
    sent = _capture_llm(monkeypatch, AnalysisOutput(brands=[]))
    llm_module.analyze_with_llm("Acme CRM, Hub Spot and HubSpot are all fine.", ctx)
    assert "Brands: Acme, Acme CRM, HubSpot, Hub Spot\n" in sent["user"]


def test_llm_other_brands_exclude_competitor_aliases(monkeypatch):
    _capture_llm(monkeypatch, AnalysisOutput(brands=[], other_brands=["HubSpot CRM", "Zoho"]))
    result = llm_module.analyze_with_llm("HubSpot CRM and Zoho are good picks.", HUBSPOT_ALIAS_CTX)
    assert result["other_brands"] == ["Zoho"]
