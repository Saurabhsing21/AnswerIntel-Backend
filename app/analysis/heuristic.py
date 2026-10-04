"""Deterministic, explainable rules. Used directly when no AI key is set, and as
the fallback (and hallucination guard) for the AI classifier."""

import re

RECOMMEND_CUES = (
    "recommend",
    "great choice",
    "excellent choice",
    "good choice",
    "best choice",
    "best option",
    "top pick",
    "top choice",
    "should choose",
    "go with",
    "stands out",
    "ideal for",
    "best fit",
    "strong fit",
    "is the best",
    "my pick",
)
POSITIVE_WORDS = (
    "excellent", "great", "good", "best", "amazing", "outstanding", "strong",
    "easy", "fast", "clean", "popular", "reliable", "flexible", "generous",
    "solid", "intuitive", "powerful", "affordable", "loved",
)
NEGATIVE_WORDS = (
    "bad", "poor", "worst", "terrible", "awful", "disappointing", "limited",
    "expensive", "lacks", "slow", "complex", "difficult", "clunky", "outdated",
    "weak", "buggy", "steep", "pricey",
)
# Splits a sentence into clauses so "X is fine, but I recommend Y" credits only Y.
CLAUSE_SPLIT = re.compile(r",|;|\bbut\b|\bhowever\b|\bwhereas\b|\binstead\b|\balthough\b|\bthough\b", re.I)
LIST_ITEM = re.compile(r"^\s*(?:#+\s*)?(?:\*\*)?(\d{1,2})[.)]\s+(.*)$")


def name_pattern(name: str) -> re.Pattern:
    return re.compile(rf"(?<![\w-]){re.escape(name)}(?![\w-])", re.I)


def sentences(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        out.extend(s for s in re.split(r"(?<=[.!?])\s+", line.strip()) if s)
    return out


def ranked_items(text: str) -> list[tuple[int, str]]:
    return [(int(m.group(1)), m.group(2)) for line in text.splitlines() if (m := LIST_ITEM.match(line))]


def _words(text: str, words: tuple[str, ...]) -> int:
    lower = text.lower()
    return sum(1 for w in words if re.search(rf"\b{re.escape(w)}\b", lower))


def analyze_name(text: str, name: str, aliases: list[str] | None = None) -> dict:
    patterns = [name_pattern(n) for n in [name, *(aliases or [])] if n]
    hits = sum(len(p.findall(text)) for p in patterns)
    if not hits:
        return {"mentioned": False, "recommended": False, "position": None, "sentiment": None, "mention_count": 0}

    def has_name(s: str) -> bool:
        return any(p.search(s) for p in patterns)

    position = next((rank for rank, item in ranked_items(text) if has_name(item)), None)

    own_sentences = [s for s in sentences(text) if has_name(s)]
    recommended = any(
        has_name(clause) and any(cue in clause.lower() for cue in RECOMMEND_CUES)
        for s in own_sentences
        for clause in CLAUSE_SPLIT.split(s)
    )
    # Being one of the top three picks in a ranked answer is a recommendation.
    if position is not None and position <= 3:
        recommended = True

    positive = sum(_words(s, POSITIVE_WORDS) for s in own_sentences)
    negative = sum(_words(s, NEGATIVE_WORDS) for s in own_sentences)
    sentiment = "positive" if positive > negative else "negative" if negative > positive else "neutral"

    return {
        "mentioned": True,
        "recommended": recommended,
        "position": position,
        "sentiment": sentiment,
        "mention_count": hits,
    }
