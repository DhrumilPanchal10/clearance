"""Illustrative per-tier token prices for cost estimation (plan Phase 10).

Prices are **per model tier**, not per hardcoded model name (the concrete model
behind each tier is resolved from config). Values are representative USD per 1M
tokens for a small/strong/judge split and are used only for the offline cost
*estimate* in ``evals.cost`` — real spend comes from the provider's billed usage
recorded on :class:`agentcore.cost.RunCost`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TierPrice:
    input_per_1m: float
    output_per_1m: float
    # Fraction of the input price charged for a cached-prefix token.
    cached_input_multiplier: float = 0.25


# Representative pricing for a flash-class "small/judge" tier and a stronger tier.
TIER_PRICES: dict[str, TierPrice] = {
    "small": TierPrice(input_per_1m=0.10, output_per_1m=0.40),
    "judge": TierPrice(input_per_1m=0.10, output_per_1m=0.40),
    "strong": TierPrice(input_per_1m=0.60, output_per_1m=2.40),
}


def cost_usd(tier: str, *, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
    """Estimate the USD cost of one call at ``tier`` with prompt caching."""
    price = TIER_PRICES.get(tier, TIER_PRICES["strong"])
    billable_input = max(0, input_tokens - cached_tokens)
    return (
        billable_input * price.input_per_1m
        + cached_tokens * price.input_per_1m * price.cached_input_multiplier
        + output_tokens * price.output_per_1m
    ) / 1_000_000
