"""Fetch URLs that users typed in, without letting them reach our internal network (SSRF).

Limits: http(s) only, ports 80/443, no credentials in the URL, every resolved address must be public,
redirects are re-validated hop by hop, short timeout, capped body. Residual risk: DNS can change between
the check and the connection; the requests are read-only GETs and the body is never returned to users.
"""

import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx

ALLOWED_PORTS = {80, 443}
USER_AGENT = "SeenLensBot/1.0 (+https://seenlens.com)"


class UnsafeURL(ValueError):
    pass


def is_public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:  # ::ffff:10.0.0.1 is still 10.0.0.1
        ip = ip.ipv4_mapped
    return ip.is_global


def validate_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UnsafeURL("Only http and https URLs are allowed.")
    if not parts.hostname:
        raise UnsafeURL("The URL has no host.")
    if parts.username or parts.password:
        raise UnsafeURL("Credentials in URLs are not allowed.")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise UnsafeURL("Invalid port.") from exc
    if port not in ALLOWED_PORTS:
        raise UnsafeURL("Only ports 80 and 443 are allowed.")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise UnsafeURL("The host could not be resolved.") from exc
    if not addresses or not all(is_public_address(a) for a in addresses):
        raise UnsafeURL("The host resolves to a non-public address.")


def safe_get(url: str, timeout: float = 5.0, max_bytes: int = 200_000, max_redirects: int = 3) -> tuple[int, str] | None:
    """GET a user-supplied URL. Returns (status, text), or None if it is unsafe, unreachable or redirects too much."""
    try:
        with httpx.Client(follow_redirects=False, timeout=timeout, headers={"User-Agent": USER_AGENT}) as client:
            for _ in range(max_redirects + 1):
                validate_url(url)
                with client.stream("GET", url) as response:
                    location = response.headers.get("location")
                    if response.is_redirect and location:
                        url = urljoin(url, location)
                        continue
                    body = b""
                    for chunk in response.iter_bytes():
                        body += chunk
                        if len(body) >= max_bytes:
                            break
                    return response.status_code, body[:max_bytes].decode("utf-8", "replace")
    except (UnsafeURL, httpx.HTTPError):
        return None
    return None
