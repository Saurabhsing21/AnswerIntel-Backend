from dataclasses import dataclass
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


class TemplatePromptGenerator(PromptGenerator):

    def generate(self, data: PromptInput) -> list[dict]:
        prompts = []

        prompts.append({
            "text": f"What are the best {data.category} options in {data.country}?",
            "category": "CATEGORY",
            "intent": "DISCOVERY",
        })

        prompts.append({
            "text": f"What are the best {data.category} options for beginners?",
            "category": "CATEGORY",
            "intent": "DISCOVERY",
        })

        prompts.append({
            "text": f"What are alternatives to {data.brand_name}?",
            "category": "ALTERNATIVE",
            "intent": "REPLACEMENT",
        })

        prompts.append({
            "text": f"What are the best alternatives to {data.brand_name}?",
            "category": "ALTERNATIVE",
            "intent": "REPLACEMENT",
        })

        for competitor in data.competitors:
            prompts.append({
                "text": f"{data.brand_name} vs {competitor}: which is better?",
                "category": "COMPARISON",
                "intent": "COMPARISON",
            })

            prompts.append({
                "text": f"What are alternatives to {competitor}?",
                "category": "COMPETITOR",
                "intent": "COMPARISON",
            })

        return prompts


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

    prompts = [
        prompt
        for prompt in prompts
        if validate_prompt(prompt)
    ]

    prompts = deduplicate_prompts(prompts)

    return prompts



    # app/prompts/generator.py




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


class TemplatePromptGenerator(PromptGenerator):

    def generate(self, data: PromptInput) -> list[dict]:

        prompts = []

        # --------------------------------------------------
        # 1. CATEGORY / DISCOVERY
        # --------------------------------------------------

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

        # --------------------------------------------------
        # 2. ALTERNATIVE / REPLACEMENT
        # --------------------------------------------------

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

        # --------------------------------------------------
        # 3. USE CASE
        # --------------------------------------------------

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

        # --------------------------------------------------
        # 4. PROBLEM
        # --------------------------------------------------

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

        # --------------------------------------------------
        # 5. BUYER INTENT
        # --------------------------------------------------

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

        # --------------------------------------------------
        # 6. BRAND-SPECIFIC
        # --------------------------------------------------

        prompts.extend([
            {
                "text": f"What is {data.brand_name}?",
                "category": "CATEGORY",
                "intent": "DISCOVERY",
            },
            {
                "text": f"Is {data.brand_name} a good {data.category}?",
                "category": "CATEGORY",
                "intent": "DISCOVERY",
            },
            {
                "text": f"Who should use {data.brand_name}?",
                "category": "USE_CASE",
                "intent": "DISCOVERY",
            },
            {
                "text": f"What are the pros and cons of {data.brand_name}?",
                "category": "CATEGORY",
                "intent": "DISCOVERY",
            },
        ])

        # --------------------------------------------------
        # 7. COMPETITOR / COMPARISON
        # --------------------------------------------------

        for competitor in data.competitors:

            prompts.extend([
                {
                    "text": (
                        f"{data.brand_name} vs {competitor}: "
                        f"which is better?"
                    ),
                    "category": "COMPARISON",
                    "intent": "COMPARISON",
                },
                {
                    "text": (
                        f"What is the difference between "
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
                    "text": (
                        f"What are alternatives to {competitor}?"
                    ),
                    "category": "COMPETITOR",
                    "intent": "COMPARISON",
                },
            ])

        return prompts