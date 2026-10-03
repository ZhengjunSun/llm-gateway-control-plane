import unittest

from llm_gateway import Gateway, GatewayRequest, MockProvider, TenantPolicy


class GatewayTests(unittest.TestCase):
    def gateway(self, primary_failures=0):
        return Gateway(
            {"a": MockProvider("a", "A", failures=primary_failures), "b": MockProvider("b", "B")},
            {"fast": [("a", "a-model"), ("b", "b-model")]},
            {"tenant": TenantPolicy(requests_per_minute=3, monthly_budget_usd=1)},
            {"a-model": (1, 2), "b-model": (1, 2)},
        )

    def request(self, temperature=0.0):
        return GatewayRequest("tenant", "fast", ({"role": "user", "content": "hello"},), temperature)

    def test_primary_provider(self):
        self.assertEqual(self.gateway().complete(self.request()).provider, "a")

    def test_fallback(self):
        self.assertEqual(self.gateway(primary_failures=1).complete(self.request()).provider, "b")

    def test_deterministic_cache(self):
        gateway = self.gateway()
        gateway.complete(self.request())
        self.assertTrue(gateway.complete(self.request()).cached)

    def test_rate_limit(self):
        gateway = self.gateway()
        for index in range(3):
            gateway.complete(GatewayRequest("tenant", "fast", ({"role": "user", "content": str(index)},), 1.0))
        with self.assertRaises(RuntimeError):
            gateway.complete(GatewayRequest("tenant", "fast", ({"role": "user", "content": "four"},), 1.0))


if __name__ == "__main__":
    unittest.main()
