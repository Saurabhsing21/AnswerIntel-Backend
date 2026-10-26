"""Brand and site logos for the app (competitors, sources, projects), fetched once and cached.

The browser asks us, never a third party, so viewers' browsing is not shared; the logo comes from Google's
favicon service, which already holds an icon for nearly every public site.
"""

import re
import time

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.auth.dependencies import get_current_user
from app.common.errors import AppError
from app.users.models import User

router = APIRouter(prefix="/logos", tags=["Logos"])

DOMAIN = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
SOURCE = "https://www.google.com/s2/favicons"
CACHE_SECONDS = 7 * 24 * 3600
MAX_BYTES = 200_000
MAX_CACHED = 5000

_cache: dict[str, tuple[float, bytes | None, str]] = {}


def fetch_logo(domain: str) -> tuple[bytes | None, str]:
    """(image, content type), or (None, "") when the site has no icon. Cached either way."""
    hit = _cache.get(domain)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1], hit[2]
    image, kind = None, ""
    try:
        response = httpx.get(SOURCE, params={"domain": domain, "sz": 128}, timeout=5, follow_redirects=True)
        kind = response.headers.get("content-type", "")
        # 404 = no icon of its own (Google serves a generic globe): show the letter tile instead.
        if response.status_code == 200 and kind.startswith("image/") and len(response.content) <= MAX_BYTES:
            image = response.content
    except httpx.HTTPError:
        pass
    if len(_cache) >= MAX_CACHED:
        _cache.clear()
    _cache[domain] = (time.monotonic(), image, kind)
    return image, kind


@router.get("/{domain}")
def logo(domain: str, current_user: User = Depends(get_current_user)):
    domain = domain.lower().removeprefix("www.")
    if not DOMAIN.match(domain):
        raise AppError(400, "BAD_DOMAIN", "Not a domain.")
    image, kind = fetch_logo(domain)
    if image is None:
        raise AppError(404, "NO_LOGO", "No logo for this site.")
    return Response(image, media_type=kind, headers={"Cache-Control": "private, max-age=604800"})
