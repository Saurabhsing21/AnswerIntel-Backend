"""Logos come through our own endpoint, cached, and only for well-formed domains."""

from tests.conftest import API, signup


def test_logo_endpoint(client, monkeypatch):
    headers = signup(client, "logo")
    assert client.get(f"{API}/logos/not a domain", headers=headers).status_code == 400
    assert client.get(f"{API}/logos/127.0.0.1", headers=headers).status_code == 400
    assert client.get(f"{API}/logos/example.com", headers=headers).status_code == 404  # no icon: the app shows a letter
    monkeypatch.setattr("app.logos.router.fetch_logo", lambda domain: (b"\x89PNG...", "image/png"))
    found = client.get(f"{API}/logos/www.G2.com", headers=headers)
    assert found.status_code == 200 and found.headers["content-type"] == "image/png" and found.content == b"\x89PNG..."
    assert client.get(f"{API}/logos/g2.com").status_code == 401
