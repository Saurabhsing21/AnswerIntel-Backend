import re
from urllib.parse import urlparse

from app.analysis.base import ResponseAnalyzer

REVIEW_SITES = {"g2.com", "capterra.com", "trustradius.com", "getapp.com", "softwareadvice.com", "trustpilot.com", "gartner.com"}
DIRECTORIES = {"producthunt.com", "crunchbase.com", "alternativeto.net", "saasworthy.com", "slashdot.org", "sourceforge.net"}
NEWS = {"techcrunch.com", "forbes.com", "theverge.com", "wired.com", "businessinsider.com", "venturebeat.com",
        "reuters.com", "bloomberg.com", "cnbc.com", "nytimes.com", "zdnet.com", "pcmag.com", "techradar.com"}
SOCIAL = {"youtube.com", "x.com", "twitter.com", "linkedin.com", "facebook.com", "instagram.com", "tiktok.com", "quora.com"}
BLOGS = {"medium.com", "substack.com", "dev.to", "hashnode.com", "hubspot.com"}


def domain_of(url: str) -> str | None:
    host = urlparse(url).hostname
    if not host:
        return None
    return host[4:] if host.startswith("www.") else host


def _matches(domain: str, owner_domain: str | None) -> bool:
    return bool(owner_domain) and (domain == owner_domain or domain.endswith("." + owner_domain))


def classify(url: str, domain: str, owners: dict) -> tuple[str, bool, int | None]:
    """Returns (source_type, is_brand_owned, competitor_id)."""
    if _matches(domain, owners.get("brand")):
        return "brand_website", True, None
    for competitor_id, competitor_domain in owners.get("competitors", {}).items():
        if _matches(domain, competitor_domain):
            return "competitor_website", False, competitor_id
    path = urlparse(url).path.lower()
    base = ".".join(domain.split(".")[-2:])
    if base == "reddit.com":
        kind = "reddit"
    elif base in REVIEW_SITES:
        kind = "review_site"
    elif base in DIRECTORIES:
        kind = "directory"
    elif base in NEWS:
        kind = "news"
    elif base in SOCIAL:
        kind = "social"
    elif re.search(r"\b(vs|versus|alternatives?|compar)", path):
        kind = "comparison"
    elif domain.startswith("docs.") or "/docs" in path:
        kind = "documentation"
    elif base in BLOGS or domain.startswith("blog.") or "/blog" in path:
        kind = "blog"
    else:
        kind = "other"
    return kind, False, None


class CitationAnalyzer(ResponseAnalyzer):
    URL_PATTERN = r"https?://[^\s)\]>\"']+"

    def analyze(self, response: str, context, extra_urls: list[str] | None = None):
        urls = [u.rstrip(".,;:") for u in re.findall(self.URL_PATTERN, response)]
        urls += list(extra_urls or [])
        owners = {
            "brand": domain_of(getattr(context, "brand_website", "") or ""),
            "competitors": {
                c["id"]: domain_of(c.get("website") or "")
                for c in getattr(context, "competitors", [])
                if c.get("website")
            },
        }
        results = []
        seen: set[str] = set()
        for url in urls:
            if url in seen:
                continue
            seen.add(url)
            domain = domain_of(url)
            if not domain:
                continue
            source_type, brand_owned, competitor_id = classify(url, domain, owners)
            results.append({
                "url": url,
                "domain": domain,
                "source_type": source_type,
                "is_brand_owned": brand_owned,
                "competitor_id": competitor_id,
            })
        return results

    def _domain(self, url: str) -> str | None:
        return domain_of(url)
