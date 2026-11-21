"""Logos come through our own endpoint, cached, and only for well-formed domains."""

from app.logos.router import fetch_logo as real_fetch_logo  # conftest swaps the module attribute for a stub in every test
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


def test_a_failed_fetch_is_retried_after_an_hour_not_a_week(monkeypatch):
    from app.logos import router as logos

    now = [1000.0]
    responses = [None, b"\x89PNG..."]  # Google times out once, then answers

    class Reply:
        def __init__(self, body):
            self.status_code, self.content = (200, body) if body else (503, b"")
            self.headers = {"content-type": "image/png" if body else "text/html"}

    monkeypatch.setattr(logos.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(logos.httpx, "get", lambda *a, **k: Reply(responses.pop(0)))
    logos._cache.pop("groww.in", None)
    assert real_fetch_logo("groww.in") == (None, "text/html")
    now[0] += 60
    assert real_fetch_logo("groww.in")[0] is None  # still remembered as a miss a minute later
    now[0] += logos.MISS_CACHE_SECONDS
    assert real_fetch_logo("groww.in") == (b"\x89PNG...", "image/png")
    now[0] += 24 * 3600
    assert real_fetch_logo("groww.in")[0] == b"\x89PNG..."  # a found logo is kept a week, no new fetch
    logos._cache.pop("groww.in", None)


def test_blurred_preview_is_a_tiny_png(monkeypatch):
    import base64, io
    from PIL import Image
    from app.logos import router as logos

    buf = io.BytesIO(); Image.new("RGB", (64, 64), "red").save(buf, format="PNG")
    monkeypatch.setattr(logos, "fetch_logo", lambda domain: (buf.getvalue(), "image/png"))
    uri = logos.blurred_preview("example.com")
    assert uri.startswith("data:image/png;base64,")
    assert Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))).size == (8, 8)
