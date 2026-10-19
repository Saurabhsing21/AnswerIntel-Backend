"""How much a rate can move from sampling alone. AI answers vary run to run, so a small change between two
scans is often noise; these are the checks the dashboard and experiments use before calling it a change."""

from math import sqrt

Z = 1.96  # 95%


def margin(rate: float | None, n: int) -> float | None:
    """Half-width of the 95% Wilson interval for a rate measured on n answers."""
    if rate is None or n <= 0:
        return None
    denom = 1 + Z * Z / n
    return round(Z * sqrt(rate * (1 - rate) / n + Z * Z / (4 * n * n)) / denom, 4)


def significant(before: float | None, n_before: int, after: float | None, n_after: int) -> bool | None:
    """Two-proportion z-test: is the change bigger than sampling noise? None when it cannot be judged."""
    if before is None or after is None or n_before <= 0 or n_after <= 0:
        return None
    se = sqrt(before * (1 - before) / n_before + after * (1 - after) / n_after)
    if se == 0:
        return after != before
    return abs(after - before) > Z * se
