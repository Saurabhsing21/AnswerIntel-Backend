"""Why the brand is missing from an answer: every cause has evidence, and nothing is guessed."""

from app.diagnosis.service import diagnose
from tests.conftest import API, make_project, signup

SITE = "https://halden.co"


def fake_fetch(pages: dict[str, str]):
    return lambda url: (200, pages[url]) if url in pages else None


def run(mention=None, competitors=None, citations=None, pages=None, engine="chatgpt", prompt="best crm for small teams"):
    return diagnose(
        brand="Halden", website=SITE, engine=engine, prompt=prompt,
        mention=mention or {"mentioned": False, "recommended": False},
        competitors=competitors or [], citations=citations or [], fetch=fake_fetch(pages or {}),
    )


def codes(result):
    return [c["code"] for c in result["causes"]]


def test_recommended_answers_need_no_diagnosis():
    assert run(mention={"mentioned": True, "recommended": True}) == {"status": "recommended", "causes": []}


def test_robots_block_is_reported_for_the_engine_crawler_only():
    pages = {f"{SITE}/robots.txt": "User-agent: OAI-SearchBot\nDisallow: /\n"}
    for engine in ("chatgpt", "chatgpt_search"):
        blocked = run(pages=pages, engine=engine)
        assert blocked["causes"][0]["code"] == "TECHNICAL" and blocked["causes"][0]["evidence"]["agent"] == "OAI-SearchBot"
    assert "TECHNICAL" not in codes(run(pages=pages, engine="perplexity"))


def test_blocking_gptbot_does_not_hide_the_brand_from_chatgpt_search():
    pages = {f"{SITE}/robots.txt": "User-agent: GPTBot\nDisallow: /\n"}
    assert "TECHNICAL" not in codes(run(pages=pages, engine="chatgpt_search"))


def test_source_gap_lists_cited_pages_that_name_competitors_but_not_the_brand():
    cites = [
        {"url": "https://g2.com/best-crm", "domain": "g2.com"},
        {"url": "https://blog.example/crm", "domain": "blog.example"},
        {"url": "https://down.example/x", "domain": "down.example"},
    ]
    pages = {
        "https://g2.com/best-crm": "<p>Top picks: Kiteline and Vantor.</p>",
        "https://blog.example/crm": "<p>Kiteline, Vantor and Halden are all fine.</p>",
    }
    comps = [{"name": "Kiteline", "recommended": True}, {"name": "Vantor", "mentioned": True}]
    gap = next(c for c in run(competitors=comps, citations=cites, pages=pages)["causes"] if c["code"] == "SOURCE_GAP")
    assert [p["url"] for p in gap["evidence"]["pages"]] == ["https://g2.com/best-crm"]
    assert gap["evidence"]["pages"][0]["competitors"] == ["Kiteline", "Vantor"]
    assert gap["evidence"]["unreadable"] == [{"url": "https://down.example/x", "domain": "down.example"}]


def test_no_answer_page_only_when_the_sitemap_has_nothing_on_the_question():
    sitemap = f"{SITE}/sitemap.xml"
    missing = run(pages={sitemap: f"<loc>{SITE}/pricing</loc><loc>{SITE}/about</loc>"})
    assert "NO_ANSWER_PAGE" in codes(missing)
    covered = run(pages={sitemap: f"<loc>{SITE}/blog/crm-for-small-teams</loc>"})
    assert "NO_ANSWER_PAGE" not in codes(covered)
    assert "NO_ANSWER_PAGE" not in codes(run())  # no sitemap: no evidence, no claim


def test_sitemap_index_is_followed_into_up_to_five_child_sitemaps():
    index = f"{SITE}/sitemap.xml"
    children = [f"{SITE}/sitemap-{n}.xml" for n in range(1, 7)]
    pages = {index: "<sitemapindex>" + "".join(f"<sitemap><loc>{c}</loc></sitemap>" for c in children) + "</sitemapindex>"}
    for n, child in enumerate(children, 1):
        pages[child] = f"<urlset><url><loc>{SITE}/page-{n}</loc></url><url><loc>{SITE}/other-{n}</loc></url></urlset>"
    pages[children[5]] = f"<urlset><url><loc>{SITE}/blog/crm-for-small-teams</loc></url></urlset>"  # sixth child is never read
    cause = next(c for c in run(pages=pages)["causes"] if c["code"] == "NO_ANSWER_PAGE")
    # 5 children x 2 pages: the 6 child-sitemap addresses are not counted as pages.
    assert cause["evidence"]["pages_checked"] == 10
    assert "None of the 10 page addresses in your sitemap matches this question" in cause["detail"]


def test_page_found_in_a_child_sitemap_means_no_gap_and_a_dead_child_is_skipped():
    index = f"{SITE}/sitemap.xml"
    pages = {
        index: f"<sitemapindex><sitemap><loc>{SITE}/gone.xml</loc></sitemap><sitemap><loc>{SITE}/posts.xml</loc></sitemap></sitemapindex>",
        f"{SITE}/posts.xml": f"<urlset><url><loc>{SITE}/blog/crm-for-small-teams</loc></url></urlset>",
    }
    assert "NO_ANSWER_PAGE" not in codes(run(pages=pages))


def test_sitemap_total_is_capped_at_200_addresses_across_children():
    index = f"{SITE}/sitemap.xml"
    pages = {index: f"<sitemapindex><sitemap><loc>{SITE}/a.xml</loc></sitemap><sitemap><loc>{SITE}/b.xml</loc></sitemap></sitemapindex>"}
    for name in ("a", "b"):
        pages[f"{SITE}/{name}.xml"] = "<urlset>" + "".join(f"<url><loc>{SITE}/{name}-{n}</loc></url>" for n in range(150)) + "</urlset>"
    cause = next(c for c in run(pages=pages)["causes"] if c["code"] == "NO_ANSWER_PAGE")
    assert cause["evidence"]["pages_checked"] == 200


def test_winning_criteria_quote_the_answer_and_mentioned_brands_get_positioning_help():
    comps = [{"name": "Kiteline", "recommended": True, "reason": "free plan", "evidence": "Kiteline has a free plan."}]
    result = run(mention={"mentioned": True, "recommended": False, "evidence": "Halden is also an option."}, competitors=comps)
    assert result["status"] == "mentioned"
    assert codes(result) == ["WINNING_CRITERIA", "NOT_RECOMMENDED"]
    assert result["causes"][0]["evidence"]["winners"][0]["quote"] == "Kiteline has a free plan."


def test_diagnosis_endpoint_is_scoped_to_the_project(client):
    headers = signup(client, "diagnosis")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    scan = client.post(f"{API}/projects/{project_id}/scans", headers=headers).json()
    responses = client.get(f"{API}/projects/{project_id}/scans/{scan['id']}/responses", headers=headers).json()
    result = client.get(f"{API}/projects/{project_id}/responses/{responses[0]['id']}/diagnosis", headers=headers)
    assert result.status_code == 200 and result.json()["status"] in {"recommended", "mentioned", "absent"}

    other = signup(client, "diagnosis-other")
    other_project = make_project(client, other)
    stolen = client.get(f"{API}/projects/{other_project}/responses/{responses[0]['id']}/diagnosis", headers=other)
    assert stolen.status_code == 404
