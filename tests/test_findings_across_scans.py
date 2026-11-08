"""Findings are confirmed across scans: one unlucky run must not create, fix or worsen a gap."""

from app.metrics.service import Observation
from app.opportunities import service
from app.opportunities.service import detect
from tests.conftest import API, make_project, signup

COMPETITORS = {1: "Kiteline"}
ENGINES = ("chatgpt", "perplexity")
SAME = object()


def answer(n, engine, scan_prompt_id, prompt_id, lost, text, category="CATEGORY"):
    return Observation(
        response_id=n, engine=engine, scan_prompt_id=scan_prompt_id, prompt_id=prompt_id, prompt_text=text, category=category,
        brand={"mentioned": not lost, "recommended": not lost, "position": None, "sentiment": None},
        competitors={1: {"mentioned": True, "recommended": True, "position": 1, "sentiment": "positive",
                         "reason": "cheap", "evidence": None}} if lost else {},
    )


def scan(questions: dict[int, tuple], offset=0, prompt_id=SAME, category="CATEGORY") -> list[Observation]:
    """One scan: {question: engines it was lost on}, each asked on both engines. Scan prompt ids differ per scan
    (offset); the prompt id stays the same. One won question keeps the scan from being only the gap."""
    rows, n = [], offset
    for q, lost_on in {**questions, 99: ()}.items():
        for engine in ENGINES:
            n += 1
            rows.append(answer(n, engine, q + offset, q if prompt_id is SAME else prompt_id, engine in lost_on,
                               f"best crm question {q}", category))
    return rows


def gap(found, category="CATEGORY"):
    return next(f for f in found if f["type"] == "COMPETITOR_GAP" and f["evidence"]["category"] == category)


def test_a_single_lost_run_is_unconfirmed():
    now = scan({1: ENGINES})
    alone = gap(detect(now, "Halden", COMPETITORS))
    assert alone["evidence"]["confirmed"] is False
    assert alone["evidence"]["questions"][0]["scans_lost"] == 1 and alone["evidence"]["questions"][0]["scans_seen"] == 1
    assert alone["evidence"]["consistency"] == "Lost in 1 of 1 scan, on 2 of 2 engines"
    # Won in both earlier scans: still only one lost run in three.
    history = [scan({1: ()}, offset=100), scan({1: ()}, offset=200)]
    once = gap(detect(now, "Halden", COMPETITORS, history=history))
    q = once["evidence"]["questions"][0]
    assert (q["scans_lost"], q["scans_seen"]) == (1, 3) and once["evidence"]["confirmed"] is False
    assert once["evidence"]["consistency"] == "Lost in 1 of 3 scans, on 2 of 2 engines"
    assert once["confidence"] == 0.33  # 1 lost (question, scan) pair out of 3


def test_lost_in_two_of_three_scans_is_confirmed():
    history = [scan({1: ("chatgpt",)}, offset=100), scan({1: ()}, offset=200)]
    found = gap(detect(scan({1: ENGINES}), "Halden", COMPETITORS, history=history))
    q = found["evidence"]["questions"][0]
    assert (q["scans_lost"], q["scans_seen"]) == (2, 3) and found["evidence"]["confirmed"] is True
    assert found["evidence"]["consistency"] == "Lost in 2 of 3 scans, on 2 of 2 engines"
    assert found["confidence"] == 0.67
    # Lost every time: the confidence is capped.
    history = [scan({1: ENGINES}, offset=100), scan({1: ENGINES}, offset=200)]
    always = gap(detect(scan({1: ENGINES}), "Halden", COMPETITORS, history=history))
    assert always["confidence"] == 0.95 and always["evidence"]["consistency"] == "Lost in 3 of 3 scans, on 2 of 2 engines"


def test_questions_match_across_scans_by_prompt_then_by_text():
    now = scan({1: ENGINES})
    assert gap(detect(now, "Halden", COMPETITORS, history=[scan({1: ENGINES}, offset=100)]))["evidence"]["confirmed"] is True
    # Same text but another prompt: a different question.
    other = scan({1: ENGINES}, offset=100, prompt_id=7)
    assert gap(detect(now, "Halden", COMPETITORS, history=[other]))["evidence"]["questions"][0]["scans_seen"] == 1
    # A question whose prompt was deleted has no prompt id: matched by its text.
    no_id = scan({1: ENGINES}, offset=100, prompt_id=None)
    assert gap(detect(scan({1: ENGINES}, prompt_id=None), "Halden", COMPETITORS, history=[no_id]))["evidence"]["confirmed"] is True


def test_confirmed_gaps_come_before_unconfirmed_ones_of_the_same_impact():
    # USE_CASE loses more answers now, but only this once; CATEGORY was lost before too.
    now = scan({1: ENGINES}) + scan({2: ENGINES, 3: ENGINES}, offset=10, category="USE_CASE")
    before = scan({1: ENGINES}, offset=100) + scan({2: (), 3: ()}, offset=110, category="USE_CASE")
    found = [f for f in detect(now, "Halden", COMPETITORS, history=[before]) if f["type"] == "COMPETITOR_GAP"]
    assert [f["impact"] for f in found] == ["high", "high"]
    assert [(f["evidence"]["category"], f["evidence"]["confirmed"], f["evidence"]["answers_lost"]) for f in found] == [
        ("CATEGORY", True, 2), ("USE_CASE", False, 4),
    ]


# ---- trends across stored scans -------------------------------------------------------------------------------

def question_gap(lost, total=4, category="CATEGORY"):
    return {"type": "COMPETITOR_GAP", "title": f"gap {category}", "description": "d", "recommended_action": "a", "impact": "medium",
            "confidence": 0.6, "evidence": {
                "category": category, "prompts": ["best app"], "answers_lost": lost, "confirmed": True,
                "questions": [{"text": "best app", "category": category, "engines_lost": lost, "engines_total": total,
                               "winners": [], "cited_domains": []}]}}


def run_scans(client, name, gaps_per_scan):
    headers = signup(client, name)
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    real, seen = service.detect, []
    try:
        for gaps in gaps_per_scan:
            service.detect = lambda *a, gaps=gaps, **k: [dict(g, evidence=dict(g["evidence"])) for g in gaps]
            client.post(f"{API}/projects/{project_id}/scans", headers=headers)
            rows = client.get(f"{API}/projects/{project_id}/opportunities", headers=headers).json()
            seen.append({r["title"]: r for r in rows})
            if len(seen) == 1 and rows:  # the user is working on it
                client.patch(f"{API}/projects/{project_id}/opportunities/{rows[0]['id']}", json={"status": "in_progress"}, headers=headers)
    finally:
        service.detect = real
    return seen


def test_a_gap_gone_once_is_improving_and_gone_twice_is_resolved(client):
    first, second, third = run_scans(client, "goneonce", [[question_gap(2)], [], []])
    assert first["gap CATEGORY"]["trend"] == "new"
    improving = second["gap CATEGORY"]
    assert improving["trend"] == "improving" and improving["status"] == "in_progress"
    assert improving["first_seen_scan_id"] == first["gap CATEGORY"]["scan_id"]
    assert third["gap CATEGORY"]["trend"] == "resolved" and third["gap CATEGORY"]["status"] == "completed"


def test_a_gap_that_comes_back_after_one_miss_keeps_its_history(client):
    first, second, third = run_scans(client, "comeback", [[question_gap(2)], [], [question_gap(2)]])
    assert second["gap CATEGORY"]["trend"] == "improving"
    back = third["gap CATEGORY"]
    assert back["trend"] == "open" and back["status"] == "in_progress" and back["first_seen_scan_id"] == first["gap CATEGORY"]["scan_id"]


def test_better_and_worse_need_a_change_bigger_than_noise(client):
    _, small = run_scans(client, "smallchange", [[question_gap(1)], [question_gap(2)]])
    assert small["gap CATEGORY"]["trend"] == "open"  # 1 -> 2 answers lost of 4 is noise
    _, big = run_scans(client, "bigchange", [[question_gap(1, total=20)], [question_gap(18, total=20)]])
    assert big["gap CATEGORY"]["trend"] == "worse"
    _, fixed = run_scans(client, "bigfix", [[question_gap(18, total=20)], [question_gap(1, total=20)]])
    assert fixed["gap CATEGORY"]["trend"] == "better"


def test_scans_judge_questions_over_the_last_full_scans(client):
    headers = signup(client, "history")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    for _ in range(3):
        client.post(f"{API}/projects/{project_id}/scans", headers=headers)
    rows = client.get(f"{API}/projects/{project_id}/opportunities", headers=headers).json()
    questions = [q for o in rows if o["trend"] not in ("resolved", "improving") for q in o["evidence"].get("questions", [])]
    assert questions and all(q["scans_seen"] == 3 for q in questions)
    assert all(1 <= q["scans_lost"] <= 3 for q in questions)
