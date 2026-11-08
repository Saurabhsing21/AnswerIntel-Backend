"""Other names for a brand or competitor ("HubSpot CRM" for "HubSpot"), so an answer that uses one is not missed."""

MAX_ALIASES = 5
MAX_ALIAS_LENGTH = 60


def check_aliases(values: list[str] | None) -> list[str] | None:
    """Trimmed, without blanks or repeats (ignoring case); raises when over the limits."""
    if values is None:
        return None
    cleaned: list[str] = []
    for value in values:
        value = value.strip()
        if value and value.lower() not in {c.lower() for c in cleaned}:
            cleaned.append(value)
    if len(cleaned) > MAX_ALIASES:
        raise ValueError(f"Add at most {MAX_ALIASES} other names.")
    if any(len(a) > MAX_ALIAS_LENGTH for a in cleaned):
        raise ValueError(f"Each other name can be at most {MAX_ALIAS_LENGTH} characters.")
    return cleaned
