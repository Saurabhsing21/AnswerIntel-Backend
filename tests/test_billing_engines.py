"""Each plan scans a fixed set of engines; the rest of the catalog is locked and names the plan that unlocks it."""

from datetime import datetime, timezone

import pytest

from app.billing.models import Subscription
from app.billing.plans import GROWTH_ENGINES, PRO_ENGINES, check_engine_choice, engines_for, entitlements_for
from app.common.errors import AppError
from app.providers.models import CATALOG, ModelConfig


def ent(plan: str):
    return entitlements_for(Subscription(plan=plan, status="active", interval="month"), datetime.now(timezone.utc))


@pytest.mark.parametrize("plan,allowed", [
    ("free", ("chatgpt_search",)),
    ("starter", ("chatgpt_search", "perplexity")),
    ("growth", GROWTH_ENGINES),
    ("pro", PRO_ENGINES),
    ("trial", GROWTH_ENGINES),
    ("none", ()),
])
def test_each_plan_allows_its_engines_and_locks_the_rest_of_the_catalog(plan, allowed):
    e = ent(plan)
    assert e.allowed_engines == allowed
    assert set(e.locked_engines) == {c.key for c in CATALOG} - set(allowed)


def test_locked_engines_name_the_cheapest_plan_that_unlocks_them():
    pro_only = {"gemini": "pro", "deepseek": "pro", "llama": "pro", "mistral": "pro"}
    assert ent("free").engine_upgrades == {"perplexity": "starter", "claude": "growth", **pro_only}
    assert ent("starter").engine_upgrades == {"claude": "growth", **pro_only}
    assert ent("pro").engine_upgrades == {}


def test_scans_skip_engines_the_plan_does_not_allow():
    saved = [ModelConfig("chatgpt_search", "m", "ChatGPT Search"), ModelConfig("claude", "m", "Claude")]
    assert [m.key for m in engines_for(saved, ent("starter"))] == ["chatgpt_search"]
    assert engines_for(saved, ent("none")) == []


def test_engine_choice_error_names_the_plan():
    check_engine_choice(ent("growth"), ["chatgpt_search", "claude"])
    with pytest.raises(AppError) as err:
        check_engine_choice(ent("starter"), ["claude"])
    assert err.value.message == "Claude is on the Growth plan." and err.value.limit == "engines"
    with pytest.raises(AppError) as err:
        check_engine_choice(ent("pro"), ["grok"])
    assert err.value.message == "Grok is not included in any plan."
