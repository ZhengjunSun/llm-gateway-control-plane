from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Protocol

from .policy import PolicyEngine, TenantPolicy


@dataclass(frozen=True)
class GatewayRequest:
    tenant: str
    model: str
    messages: tuple[dict, ...]
    temperature: float = 0.0


@dataclass(frozen=True)
class GatewayResponse:
    request_id: str
    model: str
    provider: str
    content: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    cached: bool = False


class Provider(Protocol):
    name: str
    def complete(self, model: str, messages: tuple[dict, ...], temperature: float) -> tuple[str, int, int]: ...


class MockProvider:
    def __init__(self, name: str, response: str = "synthetic response", failures: int = 0) -> None:
        self.name = name
        self.response = response
        self.failures = failures
        self.calls = 0

    def complete(self, model: str, messages: tuple[dict, ...], temperature: float) -> tuple[str, int, int]:
        self.calls += 1
        if self.calls <= self.failures:
            raise ConnectionError(f"{self.name} unavailable")
        input_tokens = sum(max(1, len(str(message.get("content", ""))) // 4) for message in messages)
        return self.response, input_tokens, max(1, len(self.response) // 4)


class CircuitBreaker:
    def __init__(self, threshold: int = 2, cooldown_seconds: float = 30.0) -> None:
        self.threshold = threshold
        self.cooldown_seconds = cooldown_seconds
        self.failures = 0
        self.opened_at: float | None = None

    def available(self, now: float | None = None) -> bool:
        current = now if now is not None else time.time()
        if self.opened_at is None:
            return True
        if current - self.opened_at >= self.cooldown_seconds:
            self.failures = 0
            self.opened_at = None
            return True
        return False

    def success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = time.time()


class Gateway:
    def __init__(self, providers: dict[str, Provider], routes: dict[str, list[tuple[str, str]]], policies: dict[str, TenantPolicy], prices: dict[str, tuple[float, float]]) -> None:
        self.providers = providers
        self.routes = routes
        self.policy = PolicyEngine(policies)
        self.prices = prices
        self.breakers = {name: CircuitBreaker() for name in providers}
        self.cache: dict[str, GatewayResponse] = {}
        self.audit: list[dict] = []

    def complete(self, request: GatewayRequest) -> GatewayResponse:
        estimated_tokens = sum(max(1, len(str(m.get("content", ""))) // 4) for m in request.messages)
        self.policy.authorize(request.tenant, estimated_tokens)
        cache_key = self._cache_key(request)
        if request.temperature == 0 and cache_key in self.cache:
            cached = self.cache[cache_key]
            return GatewayResponse(**{**cached.__dict__, "request_id": uuid.uuid4().hex, "cached": True})
        if request.model not in self.routes:
            raise KeyError(f"unknown model alias: {request.model}")
        errors = []
        for provider_name, provider_model in self.routes[request.model]:
            breaker = self.breakers[provider_name]
            if not breaker.available():
                errors.append(f"{provider_name}:circuit_open")
                continue
            try:
                content, input_tokens, output_tokens = self.providers[provider_name].complete(provider_model, request.messages, request.temperature)
                breaker.success()
                input_price, output_price = self.prices[provider_model]
                cost = input_tokens / 1_000_000 * input_price + output_tokens / 1_000_000 * output_price
                self.policy.charge(request.tenant, cost)
                response = GatewayResponse(uuid.uuid4().hex, request.model, provider_name, content, input_tokens, output_tokens, cost)
                if request.temperature == 0:
                    self.cache[cache_key] = response
                self.audit.append({"request_id": response.request_id, "tenant": request.tenant, "model": request.model, "provider": provider_name, "cost_usd": round(cost, 8), "status": "success"})
                return response
            except Exception as exc:
                breaker.failure()
                errors.append(f"{provider_name}:{type(exc).__name__}")
        self.audit.append({"tenant": request.tenant, "model": request.model, "status": "failed", "errors": errors})
        raise RuntimeError("all providers failed: " + ", ".join(errors))

    @staticmethod
    def _cache_key(request: GatewayRequest) -> str:
        payload = json.dumps({"model": request.model, "messages": request.messages, "temperature": request.temperature}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()
