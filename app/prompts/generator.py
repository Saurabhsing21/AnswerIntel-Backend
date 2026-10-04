from dataclasses import dataclass


@dataclass
class PromptInput:
    brand_name: str
    category: str
    country: str
    description: str | None
    competitors: list[str]


class PromptGenerator:
    def generate(self, data: PromptInput) -> list[dict]:
        raise NotImplementedError


VALID_CATEGORIES = {
    "CATEGORY",
    "COMPARISON",
    "ALTERNATIVE",
    "USE_CASE",
    "PROBLEM",
    "BUYER_INTENT",
    "COMPETITOR",
}

VALID_INTENTS = {
    "DISCOVERY",
    "COMPARISON",
    "REPLACEMENT",
    "PURCHASE",
    "PROBLEM_SOLVING",
}


class TemplatePromptGenerator(PromptGenerator):

    def generate(self, data: PromptInput) -> list[dict]:
        prompts = []

        prompts.extend([
            {
                "text": f"What are the best {data.category} options in {data.country}?",
                "category": "CATEGORY",
                "intent": "DISCOVERY",
            },
            {
                "text": f"What are the most popular {data.category} products?",
                "category": "CATEGORY",
                "intent": "DISCOVERY",
            },
            {
                "text": f"What are the best {data.category} for small businesses?",
                "category": "CATEGORY",
                "intent": "DISCOVERY",
            },
            {
                "text": f"What are the best {data.category} for beginners?",
                "category": "CATEGORY",
                "intent": "DISCOVERY",
            },
            {
                "text": f"What {data.category} should a new business consider?",
                "category": "CATEGORY",
                "intent": "DISCOVERY",
            },
        ])

        prompts.extend([
            {
                "text": f"What are alternatives to {data.brand_name}?",
                "category": "ALTERNATIVE",
                "intent": "REPLACEMENT",
            },
            {
                "text": f"What are the best alternatives to {data.brand_name}?",
                "category": "ALTERNATIVE",
                "intent": "REPLACEMENT",
            },
            {
                "text": f"What are cheaper alternatives to {data.brand_name}?",
                "category": "ALTERNATIVE",
                "intent": "REPLACEMENT",
            },
            {
                "text": f"What are the best {data.category} alternatives to {data.brand_name}?",
                "category": "ALTERNATIVE",
                "intent": "REPLACEMENT",
            },
        ])

        prompts.extend([
            {
                "text": f"What is the best {data.category} for a small team?",
                "category": "USE_CASE",
                "intent": "DISCOVERY",
            },
            {
                "text": f"What is the best {data.category} for startups?",
                "category": "USE_CASE",
                "intent": "DISCOVERY",
            },
            {
                "text": f"What is the best {data.category} for growing businesses?",
                "category": "USE_CASE",
                "intent": "DISCOVERY",
            },
            {
                "text": f"What {data.category} is easiest to get started with?",
                "category": "USE_CASE",
                "intent": "DISCOVERY",
            },
            {
                "text": f"What {data.category} is best for teams with limited resources?",
                "category": "USE_CASE",
                "intent": "DISCOVERY",
            },
        ])

        prompts.extend([
            {
                "text": f"How can a small business choose the right {data.category}?",
                "category": "PROBLEM",
                "intent": "PROBLEM_SOLVING",
            },
            {
                "text": f"What problems should I consider when choosing a {data.category}?",
                "category": "PROBLEM",
                "intent": "PROBLEM_SOLVING",
            },
            {
                "text": f"How do I compare different {data.category} options?",
                "category": "PROBLEM",
                "intent": "PROBLEM_SOLVING",
            },
            {
                "text": f"What should I look for when buying {data.category}?",
                "category": "PROBLEM",
                "intent": "PROBLEM_SOLVING",
            },
        ])

        prompts.extend([
            {
                "text": f"Which {data.category} should I buy?",
                "category": "BUYER_INTENT",
                "intent": "PURCHASE",
            },
            {
                "text": f"What is the best {data.category} for the price?",
                "category": "BUYER_INTENT",
                "intent": "PURCHASE",
            },
            {
                "text": f"Which {data.category} gives the best value for money?",
                "category": "BUYER_INTENT",
                "intent": "PURCHASE",
            },
            {
                "text": f"What {data.category} would you recommend for a first-time buyer?",
                "category": "BUYER_INTENT",
                "intent": "PURCHASE",
            },
        ])

        for competitor in data.competitors:
            prompts.extend([
                {
                    "text": (
                        f"{data.brand_name} vs {competitor}: "
                        "which is better?"
                    ),
                    "category": "COMPARISON",
                    "intent": "COMPARISON",
                },
                {
                    "text": (
                        "What is the difference between "
                        f"{data.brand_name} and {competitor}?"
                    ),
                    "category": "COMPARISON",
                    "intent": "COMPARISON",
                },
                {
                    "text": (
                        f"Should I choose {data.brand_name} "
                        f"or {competitor}?"
                    ),
                    "category": "COMPARISON",
                    "intent": "COMPARISON",
                },
                {
                    "text": f"What are alternatives to {competitor}?",
                    "category": "COMPETITOR",
                    "intent": "COMPARISON",
                },
            ])

        return prompts


def validate_prompt(prompt: dict) -> bool:
    text = prompt.get("text", "").strip()
    category = prompt.get("category")
    intent = prompt.get("intent")

    if not text:
        return False

    if category not in VALID_CATEGORIES:
        return False

    if intent not in VALID_INTENTS:
        return False

    return True


def deduplicate_prompts(prompts: list[dict]) -> list[dict]:
    seen = set()
    unique_prompts = []

    for prompt in prompts:
        normalized = prompt["text"].strip().lower()

        if normalized in seen:
            continue

        seen.add(normalized)
        unique_prompts.append(prompt)

    return unique_prompts


def generate_prompts(
    generator: PromptGenerator,
    data: PromptInput,
) -> list[dict]:
    prompts = generator.generate(data)
    prompts = [prompt for prompt in prompts if validate_prompt(prompt)]
    return deduplicate_prompts(prompts)


# ---------------------------------------------------------------------------
# Prompt Discovery Agent (PRD sections 13-15). Output is validated before use.
# ---------------------------------------------------------------------------

from typing import Literal  # noqa: E402

from pydantic import BaseModel, Field  # noqa: E402

from app.common.config import settings  # noqa: E402
from app.common.llm import complete_json  # noqa: E402

DISCOVERY_SYSTEM = """You are a customer research and AI-search prompt generation agent.

Given a business, category, market, and competitors, generate realistic questions a
potential customer could ask an AI assistant like ChatGPT, Perplexity, or Gemini.

Do not generate questions that merely contain the company name (no "What is X?").
Prioritize: category discovery, commercial intent, comparison, alternatives, use cases,
customer problems, competitor discovery, and buying decisions.
Every prompt must read like a real buyer typed it. Vary wording and length. No duplicates.

Return JSON: {"prompts": [{"text": str, "category": one of CATEGORY|COMPARISON|ALTERNATIVE|USE_CASE|PROBLEM|BUYER_INTENT|COMPETITOR,
"intent": one of DISCOVERY|COMPARISON|REPLACEMENT|PURCHASE|PROBLEM_SOLVING, "importance": number 0-1 (commercial relevance)}]}"""


class DiscoveredPrompt(BaseModel):
    text: str = Field(min_length=8, max_length=300)
    category: Literal["CATEGORY", "COMPARISON", "ALTERNATIVE", "USE_CASE", "PROBLEM", "BUYER_INTENT", "COMPETITOR"]
    intent: Literal["DISCOVERY", "COMPARISON", "REPLACEMENT", "PURCHASE", "PROBLEM_SOLVING"]
    importance: float = Field(default=0.5, ge=0, le=1)


class DiscoveryOutput(BaseModel):
    prompts: list[DiscoveredPrompt] = Field(min_length=5, max_length=80)


class LLMPromptGenerator(PromptGenerator):
    def __init__(self, count: int = 40):
        self.count = count

    def generate(self, data: PromptInput) -> list[dict]:
        user = (
            f"Business: {data.brand_name}\n"
            f"Description: {data.description or 'n/a'}\n"
            f"Category: {data.category}\n"
            f"Market: {data.country}\n"
            f"Competitors: {', '.join(data.competitors) or 'none given'}\n\n"
            f"Generate {self.count} prompts covering every category."
        )
        output = complete_json(settings.prompt_model, DISCOVERY_SYSTEM, user, DiscoveryOutput)
        brand = data.brand_name.lower()
        return [
            p.model_dump()
            for p in output.prompts
            # Enforce the "not merely the company name" rule even if the model ignores it.
            if not (brand in p.text.lower() and p.category not in ("COMPARISON", "ALTERNATIVE"))
        ]
