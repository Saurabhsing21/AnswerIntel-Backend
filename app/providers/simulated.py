import hashlib
import random
from urllib.parse import urlparse

from app.providers.base import AIProvider, AIResponse, ProviderContext

# Used only when no OPENROUTER_API_KEY is configured. Responses are flagged
# as simulated in the database, the API, and the dashboard.

REASONS = [
    "fast to set up with a generous free plan",
    "strong automation for small teams",
    "clean interface that founders like",
    "good reporting, though pricing climbs as you grow",
    "flexible pipelines and solid integrations",
    "simple to learn, but reporting is limited",
]
THIRD_PARTY = [
    "https://www.g2.com/categories/{slug}",
    "https://www.reddit.com/r/startups/comments/{slug}",
    "https://www.capterra.com/{slug}-software/",
    "https://techcrunch.com/tag/{slug}/",
    "https://zapier.com/blog/best-{slug}/",
]


def _slug(text: str) -> str:
    return "-".join(text.lower().split())[:40]


class SimulatedAIProvider(AIProvider):
    @property
    def name(self) -> str:
        return "simulated"

    def ask(
        self,
        prompt: str,
        model: str,
        context: ProviderContext | None = None,
    ) -> AIResponse:
        ctx = context or ProviderContext()
        seed = int(hashlib.sha256(f"{model}|{prompt}|{ctx.variation}".encode()).hexdigest(), 16)
        rng = random.Random(seed)

        names = list(dict.fromkeys([*ctx.competitors]))
        # The brand appears in roughly 60% of answers, and is ranked anywhere.
        if ctx.brand_name and rng.random() < 0.6:
            names.insert(rng.randint(0, len(names)), ctx.brand_name)
        rng.shuffle(names)
        names = names[: rng.randint(2, max(2, min(5, len(names))))] if names else []

        lines = ["Here are the strongest options to consider:", ""]
        for i, name in enumerate(names, 1):
            lines.append(f"{i}. {name}: {rng.choice(REASONS)}.")
        if names:
            lines.append("")
            lines.append(f"For most small teams, I'd recommend {names[0]}.")
        text = "\n".join(lines)

        words = [w for w in prompt.lower().strip("?").split() if len(w) > 3]
        slug = _slug(" ".join(words[-2:]) if words else "software")
        citations = [rng.choice(THIRD_PARTY).format(slug=slug) for _ in range(rng.randint(1, 3))]
        if ctx.brand_website and ctx.brand_name in names and rng.random() < 0.4:
            host = urlparse(ctx.brand_website).hostname or ""
            citations.append(f"https://{host}/")
        citations = list(dict.fromkeys(citations))

        return AIResponse(
            provider=self.name,
            model=model,
            prompt=prompt,
            text=text,
            raw_response={"simulated": True, "citations": citations},
            citations=citations,
            latency_ms=rng.randint(400, 2400),
        )
