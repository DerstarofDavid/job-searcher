"""Search discovery providers and deep-query construction."""

from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

from .models import SearchHit, SourceHealth
from .utils import canonicalize_url, collapse_whitespace
from .webclient import WebClient


class _DuckParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.snippets: list[str] = []
        self._capture: str | None = None
        self._href = ""
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "a" and "result__a" in classes:
            self._capture, self._href, self._parts = "link", attributes.get("href") or "", []
        elif tag in {"a", "div", "span"} and "result__snippet" in classes:
            self._capture, self._parts = "snippet", []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._capture == "link" and tag == "a":
            self.links.append((collapse_whitespace(" ".join(self._parts)), self._href))
            self._capture = None
        elif self._capture == "snippet" and tag in {"a", "div", "span"}:
            self.snippets.append(collapse_whitespace(" ".join(self._parts)))
            self._capture = None


def _unwrap_duck_url(value: str) -> str:
    if value.startswith("//"):
        value = "https:" + value
    parsed = urlparse(value)
    redirect = parse_qs(parsed.query).get("uddg")
    return unquote(redirect[0]) if redirect else value


class SearchProvider:
    name = "base"

    def __init__(self, client: WebClient, max_results: int) -> None:
        self.client = client
        self.max_results = max_results

    def search(self, query: str) -> list[SearchHit]:
        raise NotImplementedError

    def should_search(self) -> bool:
        return True


class BingRssProvider(SearchProvider):
    name = "bing-rss"

    def search(self, query: str) -> list[SearchHit]:
        url = "https://www.bing.com/search?format=rss&q=" + quote_plus(query)
        response = self.client.fetch(url, obey_robots=False)
        if response.error:
            raise RuntimeError(response.error)
        try:
            root = ET.fromstring(response.body)
        except ET.ParseError as exc:
            raise RuntimeError("Bing returned non-RSS content") from exc
        hits: list[SearchHit] = []
        for rank, item in enumerate(root.findall(".//item"), start=1):
            title = collapse_whitespace(item.findtext("title") or "")
            link = collapse_whitespace(item.findtext("link") or "")
            snippet = collapse_whitespace(item.findtext("description") or "")
            if link:
                hits.append(SearchHit(title, canonicalize_url(link), snippet, self.name, query, rank))
            if len(hits) >= self.max_results:
                break
        return hits


class DuckDuckGoProvider(SearchProvider):
    name = "duckduckgo"

    def search(self, query: str) -> list[SearchHit]:
        url = "https://html.duckduckgo.com/html/?q=" + quote_plus(query)
        response = self.client.fetch(url, obey_robots=False)
        if response.error:
            raise RuntimeError(response.error)
        parser = _DuckParser()
        parser.feed(response.body)
        hits: list[SearchHit] = []
        for rank, (title, raw_url) in enumerate(parser.links, start=1):
            url = canonicalize_url(_unwrap_duck_url(raw_url))
            if not url.startswith(("http://", "https://")):
                continue
            snippet = parser.snippets[rank - 1] if rank <= len(parser.snippets) else ""
            hits.append(SearchHit(title, url, snippet, self.name, query, rank))
            if len(hits) >= self.max_results:
                break
        return hits


class TavilyProvider(SearchProvider):
    name = "tavily"

    def __init__(
        self,
        client: WebClient,
        max_results: int,
        api_key: str | None,
        max_calls: int | None = None,
    ) -> None:
        super().__init__(client, max_results)
        self.api_key = api_key
        self.max_calls = max_calls
        self.calls = 0

    def should_search(self) -> bool:
        return self.max_calls is None or self.calls < self.max_calls

    def search(self, query: str) -> list[SearchHit]:
        payload = json.dumps(
            {
                "query": query,
                "search_depth": "advanced",
                "topic": "general",
                "max_results": self.max_results,
                "include_answer": False,
                "include_raw_content": False,
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        else:
            headers["X-Tavily-Access-Mode"] = "keyless"
        self.calls += 1
        response = self.client.fetch(
            "https://api.tavily.com/search",
            method="POST",
            data=payload,
            headers=headers,
            obey_robots=False,
        )
        if response.error:
            raise RuntimeError(response.error)
        try:
            data = json.loads(response.body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Tavily returned invalid JSON") from exc
        hits: list[SearchHit] = []
        for rank, result in enumerate(data.get("results", []), start=1):
            if not result.get("url"):
                continue
            hits.append(
                SearchHit(
                    title=collapse_whitespace(result.get("title", "")),
                    url=canonicalize_url(result["url"]),
                    snippet=collapse_whitespace(result.get("content", "")),
                    source=self.name,
                    query=query,
                    rank=rank,
                    published_hint=result.get("published_date"),
                )
            )
        return hits


def build_queries(search_config: dict, mode: str) -> list[str]:
    queries = list(search_config.get("quick_queries", []))
    if mode in {"standard", "deep"}:
        queries.extend(search_config.get("standard_queries", []))
    if mode == "deep":
        source_query = search_config["source_domain_query"]
        career_query = search_config["career_domain_query"]
        queries.extend(f"site:{domain} {source_query}" for domain in search_config.get("source_domains", []))
        queries.extend(f"site:{domain} careers {career_query}" for domain in search_config.get("career_domains", []))
    return list(dict.fromkeys(query.strip() for query in queries if query.strip()))


def make_providers(
    name: str,
    client: WebClient,
    max_results: int,
    tavily_auto_max_queries: int = 12,
) -> list[SearchProvider]:
    tavily_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if name == "tavily":
        return [TavilyProvider(client, max_results, tavily_key or None)]
    if name == "bing":
        return [BingRssProvider(client, max_results)]
    if name == "duckduckgo":
        return [DuckDuckGoProvider(client, max_results)]
    if name != "auto":
        raise ValueError("Provider must be auto, bing, duckduckgo, or tavily")
    providers: list[SearchProvider] = [BingRssProvider(client, max_results), DuckDuckGoProvider(client, max_results)]
    providers.insert(
        0,
        TavilyProvider(
            client,
            max_results,
            tavily_key or None,
            tavily_auto_max_queries if tavily_key else min(8, tavily_auto_max_queries),
        ),
    )
    return providers


def discover(
    queries: list[str],
    providers: list[SearchProvider],
    progress: Callable[[str], None] | None = None,
) -> tuple[list[SearchHit], list[SourceHealth]]:
    all_hits: list[SearchHit] = []
    health = {provider.name: SourceHealth(provider.name) for provider in providers}
    for query in queries:
        for provider in providers:
            if not provider.should_search():
                continue
            status = health[provider.name]
            status.queries += 1
            if progress:
                progress(f"Searching {provider.name}: {query}")
            try:
                hits = provider.search(query)
                status.hits += len(hits)
                all_hits.extend(hits)
                if progress:
                    progress(f"  found {len(hits)} raw results")
            except Exception as exc:
                message = str(exc).strip() or exc.__class__.__name__
                if message not in status.errors:
                    status.errors.append(message[:240])
                if progress:
                    progress(f"  source warning: {message[:160]}")
    return all_hits, list(health.values())
