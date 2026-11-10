"""Cost model tests (plan T10.1/T10.2/T10.3)."""

from __future__ import annotations

from evals.cost import analyze

from agentcore.prices import TIER_PRICES, cost_usd


def test_cached_tokens_are_cheaper() -> None:
    full = cost_usd("judge", input_tokens=1000, output_tokens=50)
    cached = cost_usd("judge", input_tokens=1000, output_tokens=50, cached_tokens=900)
    assert cached < full


def test_strong_tier_pricier_than_small() -> None:
    assert TIER_PRICES["strong"].input_per_1m > TIER_PRICES["small"].input_per_1m


def test_each_lever_reduces_cost() -> None:
    lines = analyze()
    costs = [ln.per_case_usd for ln in lines]
    # Baseline → routing → compression → caching, each strictly cheaper.
    assert costs == sorted(costs, reverse=True)
    assert all(a > b for a, b in zip(costs, costs[1:], strict=False))
    # End-to-end reduction is substantial.
    assert costs[-1] < costs[0] * 0.2


def test_routing_drops_rule_criteria_calls() -> None:
    lines = analyze()
    # Routing makes fewer LLM calls than the baseline (rule criteria → 0 LLM).
    assert lines[1].llm_calls < lines[0].llm_calls
