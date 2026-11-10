"""Deterministic, scriptable failure injection for the payer service (plan T3.2).

Faults are *scripted*, not random, so the fault-injection eval (T9.4) is
reproducible: latency, 429-with-Retry-After, 500s, outage windows, and
duplicate / out-of-order webhook delivery.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field


@dataclass
class FailureConfig:
    latency_ms: int = 0
    # While True, every request returns 503 (payer outage window).
    outage: bool = False
    retry_after_s: int = 2
    # HTTP status codes to emit on successive requests before succeeding; each
    # request consumes one from the front. e.g. [429, 500] then normal service.
    inject_statuses: deque[int] = field(default_factory=deque)
    duplicate_webhooks: bool = False
    reorder_webhooks: bool = False

    def next_fault(self) -> int | None:
        """Return an HTTP error status to emit for this request, or None."""
        if self.outage:
            return 503
        if self.inject_statuses:
            return self.inject_statuses.popleft()
        return None

    async def apply_latency(self) -> None:
        if self.latency_ms > 0:
            await asyncio.sleep(self.latency_ms / 1000)


def plan_webhook_deliveries[T](events: list[T], config: FailureConfig) -> list[T]:
    """Apply duplicate / out-of-order webhook faults to an event sequence.

    Deterministic: reorder reverses the sequence; duplicate repeats the last
    event once. Used to prove our receiver dedupes by event id and tolerates
    out-of-order delivery (T7.1, T9.4).
    """
    ordered = list(reversed(events)) if config.reorder_webhooks else list(events)
    if config.duplicate_webhooks and ordered:
        ordered.append(ordered[-1])
    return ordered
