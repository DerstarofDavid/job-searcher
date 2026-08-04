from __future__ import annotations

import json
import unittest

from jobfinder.models import FetchResult
from jobfinder.search import TavilyProvider


class FakeClient:
    def __init__(self) -> None:
        self.headers = {}
        self.payload = {}

    def fetch(self, url, **kwargs):
        self.headers = kwargs["headers"]
        self.payload = json.loads(kwargs["data"])
        body = json.dumps({"results": [{"title": "Role", "url": "https://example.test/job", "content": "ERP role"}]})
        return FetchResult(url, url, 200, body, "application/json")


class TavilyTests(unittest.TestCase):
    def test_bearer_auth_and_call_cap(self) -> None:
        client = FakeClient()
        provider = TavilyProvider(client, 10, "tvly-test", max_calls=1)
        hits = provider.search("Swiss ERP role")
        self.assertEqual(len(hits), 1)
        self.assertEqual(client.headers["Authorization"], "Bearer tvly-test")
        self.assertNotIn("api_key", client.payload)
        self.assertFalse(provider.should_search())

    def test_keyless_header(self) -> None:
        client = FakeClient()
        provider = TavilyProvider(client, 10, None)
        provider.search("Swiss ERP role")
        self.assertEqual(client.headers["X-Tavily-Access-Mode"], "keyless")


if __name__ == "__main__":
    unittest.main()
