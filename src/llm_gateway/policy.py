from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class TenantPolicy:
    requests_per_minute: int = 60
    monthly_budget_usd: float = 20.0
    max_input_tokens: int = 8_000


class PolicyEngine:
    def __init__(self, policies: dict[str, TenantPolicy]) -> None:
        self.policies = policies
        self.requests: dict[str, deque[float]] = defaultdict(deque)
        self.spend: dict[str, float] = defaultdict(float)

    def authorize(self, tenant: str, input_tokens: int, now: float | None = None) -> None:
        if tenant not in self.policies:
            raise PermissionError("unknown tenant")
        policy = self.policies[tenant]
        if input_tokens > policy.max_input_tokens:
            raise ValueError("input token limit exceeded")
        if self.spend[tenant] >= policy.monthly_budget_usd:
            raise PermissionError("monthly budget exhausted")
        current = now if now is not None else time.time()
        window = self.requests[tenant]
        while window and window[0] <= current - 60:
            window.popleft()
        if len(window) >= policy.requests_per_minute:
            raise RuntimeError("rate limit exceeded")
        window.append(current)

    def charge(self, tenant: str, amount: float) -> None:
        self.spend[tenant] += amount
