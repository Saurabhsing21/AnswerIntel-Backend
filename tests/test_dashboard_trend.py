"""The dashboard trend carries every tracked competitor per scan, so the UI can chart brands side by side."""

from tests.conftest import API, make_project, signup


def test_trend_includes_each_competitor_for_every_scan(client):
    headers = signup(client, "trend")
    project_id = make_project(client, headers)
    client.post(f"{API}/projects/{project_id}/prompts/generate", headers=headers)
    client.post(f"{API}/projects/{project_id}/scans", headers=headers)
    client.post(f"{API}/projects/{project_id}/scans", headers=headers)

    trend = client.get(f"{API}/projects/{project_id}/dashboard", headers=headers).json()["trend"]
    assert len(trend) == 2
    for point in trend:
        assert set(point["competitors"]) == {"Kiteline", "Vantor"}
        for metrics in point["competitors"].values():
            assert set(metrics) == {"mention_rate", "recommendation_rate", "share_of_voice"}
            assert all(0 <= value <= 1 for value in metrics.values())
        assert 0 <= point["mention_rate"] <= 1  # the brand's own series is unchanged
