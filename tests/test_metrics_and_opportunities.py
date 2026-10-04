from app.metrics.service import Observation, calculate
from app.opportunities.service import detect


def obs(i, engine, category, brand, comps=None, cites=None, text=None):
    return Observation(
        response_id=i, engine=engine, scan_prompt_id=i // 2, prompt_id=i // 2,
        prompt_text=text or f"prompt {i // 2}", category=category,
        brand={"mentioned": brand[0], "recommended": brand[1], "position": brand[2], "sentiment": brand[3]},
        competitors=comps or {}, citations=cites or [],
    )


def comp(mentioned, recommended, position=None):
    return {"mentioned": mentioned, "recommended": recommended, "position": position, "sentiment": None}


def cite(domain, owned=False, competitor_id=None):
    return {"url": f"https://{domain}/x", "domain": domain, "source_type": "other", "is_brand_owned": owned, "competitor_id": competitor_id}


def test_metric_formulas():
    observations = [
        obs(0, "chatgpt", "CATEGORY", (True, True, 2, "positive"), {1: comp(True, True, 1)}, [cite("halden.co", owned=True)]),
        obs(1, "gemini", "CATEGORY", (True, False, None, "neutral"), {1: comp(True, True, 1)}),
        obs(2, "chatgpt", "COMPARISON", (False, False, None, None), {1: comp(True, True, 1)}),
        obs(3, "gemini", "COMPARISON", (False, False, None, None), {1: comp(False, False)}),
    ]
    m = calculate(observations, [1])
    assert m["total_responses"] == 4
    assert m["mention_rate"] == 0.5
    assert m["recommendation_rate"] == 0.25
    # 1 brand recommendation out of 1 + 3 competitor recommendations.
    assert m["share_of_voice"] == 0.25
    assert m["competitors"][1]["share_of_voice"] == 0.75
    assert m["average_position"] == 2.0
    assert m["citation_rate"] == 0.25
    assert m["positive_sentiment_rate"] == 0.5
    assert m["by_engine"]["chatgpt"]["mention_rate"] == 0.5


def test_metrics_with_no_recommendations_do_not_divide_by_zero():
    m = calculate([obs(0, "chatgpt", "CATEGORY", (False, False, None, None))], [1])
    assert m["share_of_voice"] == 0.0 and m["average_position"] is None


def test_opportunity_rules_fire_on_evidence():
    observations = [
        obs(0, "chatgpt", "ALTERNATIVE", (False, False, None, None), {1: comp(True, True)}, [cite("g2.com")], "Best Kiteline alternatives"),
        obs(1, "gemini", "ALTERNATIVE", (False, False, None, None), {1: comp(True, True)}, [cite("g2.com")], "Best Kiteline alternatives"),
        obs(2, "chatgpt", "ALTERNATIVE", (False, False, None, None), {1: comp(True, True)}, [cite("g2.com")], "Cheaper Kiteline alternatives"),
        obs(4, "chatgpt", "COMPARISON", (True, False, None, "neutral"), {1: comp(True, True)}, [], "Halden vs Kiteline"),
        obs(6, "chatgpt", "CATEGORY", (True, False, None, "neutral"), {}, [cite("producthunt.com")], "Best CRM"),
        obs(8, "chatgpt", "CATEGORY", (True, False, None, "neutral"), {}, [], "Top CRM"),
    ]
    types = {o["type"] for o in detect(observations, "Halden", {1: "Kiteline"})}
    assert {"COMPETITOR_GAP", "CITATION_GAP", "CONTENT_GAP", "POSITIONING_GAP", "COMPARISON_GAP"} <= types
    gap = next(o for o in detect(observations, "Halden", {1: "Kiteline"}) if o["type"] == "CITATION_GAP")
    assert gap["evidence"]["domains"][0]["domain"] == "g2.com"


def test_no_opportunities_when_brand_wins_everything():
    observations = [obs(i, "chatgpt", "CATEGORY", (True, True, 1, "positive"), {1: comp(True, False)}) for i in range(6)]
    assert detect(observations, "Halden", {1: "Kiteline"}) == []
