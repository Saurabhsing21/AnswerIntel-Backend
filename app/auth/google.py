"""Sign in with Google: the browser gets an ID token from Google Identity Services and we check it with Google."""

import httpx

from app.common.config import settings

TOKENINFO = "https://oauth2.googleapis.com/tokeninfo"
ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


def verified_email(id_token: str) -> str | None:
    """The Google account's email when the token is genuine, meant for us and the email is verified; else None."""
    if not settings.google_client_id:
        return None
    try:
        response = httpx.get(TOKENINFO, params={"id_token": id_token}, timeout=10)
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None  # Google rejects expired, malformed or forged tokens
    claims = response.json()
    if claims.get("aud") != settings.google_client_id or claims.get("iss") not in ISSUERS:
        return None
    if str(claims.get("email_verified")).lower() != "true" or not claims.get("email"):
        return None
    return str(claims["email"]).lower()
