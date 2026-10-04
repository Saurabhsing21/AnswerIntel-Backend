import re

from app.analysis.base import ResponseAnalyzer


class PositionAnalyzer(ResponseAnalyzer):

    def analyze(self, response: str, context):

        brand = re.escape(context.brand_name)

        pattern = rf"(?:^|\n)\s*(\d+)[.)-]\s*.*{brand}.*"

        match = re.search(
            pattern,
            response,
            flags=re.IGNORECASE,
        )

        if not match:
            return {
                "position": None,
            }

        return {
            "position": int(match.group(1)),
        }