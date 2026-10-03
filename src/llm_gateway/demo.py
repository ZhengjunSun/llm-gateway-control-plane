from dataclasses import asdict

from .gateway import Gateway, GatewayRequest, MockProvider
from .policy import TenantPolicy


def main() -> None:
    primary = MockProvider("primary", failures=1)
    fallback = MockProvider("fallback", response="fallback completed the synthetic request")
    gateway = Gateway(
        {"primary": primary, "fallback": fallback},
        {"balanced": [("primary", "model-a"), ("fallback", "model-b")]},
        {"demo": TenantPolicy(requests_per_minute=10)},
        {"model-a": (1.0, 2.0), "model-b": (0.5, 1.0)},
    )
    request = GatewayRequest("demo", "balanced", ({"role": "user", "content": "Analyze a synthetic incident"},))
    print(asdict(gateway.complete(request)))
    print(asdict(gateway.complete(request)))
    print(gateway.audit)


if __name__ == "__main__":
    main()
