import re
from urllib.parse import urlparse

from app.analysis.base import ResponseAnalyzer


class CitationAnalyzer(ResponseAnalyzer):

    URL_PATTERN = r"https?://[^\s)\]]+"

    def analyze(self, response: str, context):
        urls = re.findall(self.URL_PATTERN, response)
        return [
            {
                "url": url.rstrip(".,;"),
                "domain": self._domain(url),
            }
            for url in urls
        ]

    def _domain(self, url: str) -> str | None:
        host = urlparse(url).hostname
        if not host:
            return None
        if host.startswith("www."):
            host = host[4:]
        return host
