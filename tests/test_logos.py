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


def test_blurred_preview_is_a_tiny_png(monkeypatch):
    import base64, io
    from PIL import Image
    from app.logos import router as logos

    buf = io.BytesIO(); Image.new("RGB", (64, 64), "red").save(buf, format="PNG")
    monkeypatch.setattr(logos, "fetch_logo", lambda domain: (buf.getvalue(), "image/png"))
    uri = logos.blurred_preview("example.com")
    assert uri.startswith("data:image/png;base64,")
    assert Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))).size == (8, 8)
