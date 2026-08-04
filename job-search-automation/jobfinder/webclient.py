"""Polite standard-library HTTP client with robots.txt and rate limiting."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib import error, request, robotparser
from urllib.parse import urlparse

from .models import FetchResult


@dataclass(slots=True)
class WebClient:
    user_agent: str
    timeout: float = 18
    delay: float = 1.2
    max_bytes: int = 2_500_000
    respect_robots: bool = True
    retries: int = 2
    _last_request: dict[str, float] = field(init=False, default_factory=dict)
    _robots: dict[str, robotparser.RobotFileParser | None] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self._last_request.clear()
        self._robots.clear()

    def _pace(self, host: str) -> None:
        elapsed = time.monotonic() - self._last_request.get(host, 0.0)
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request[host] = time.monotonic()

    def _robots_allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parsed = urlparse(url)
        root = f"{parsed.scheme}://{parsed.netloc}"
        if root not in self._robots:
            robots_url = root + "/robots.txt"
            parser = robotparser.RobotFileParser()
            parser.set_url(robots_url)
            try:
                self._pace(parsed.netloc.casefold())
                req = request.Request(robots_url, headers={"User-Agent": self.user_agent})
                with request.urlopen(req, timeout=min(self.timeout, 10)) as response:
                    body = response.read(500_000).decode("utf-8", errors="replace")
                parser.parse(body.splitlines())
                self._robots[root] = parser
            except Exception:
                # A missing/unavailable robots file is treated as unspecified, not a ban.
                self._robots[root] = None
        parser = self._robots[root]
        return True if parser is None else parser.can_fetch(self.user_agent, url)

    def fetch(
        self,
        url: str,
        *,
        method: str = "GET",
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        obey_robots: bool = True,
    ) -> FetchResult:
        if obey_robots and not self._robots_allowed(url):
            return FetchResult(url, url, None, error="Blocked by robots.txt", robots_allowed=False)
        host = urlparse(url).netloc.casefold()
        request_headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.7",
            "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.7,de;q=0.6",
        }
        request_headers.update(headers or {})
        transient = {408, 425, 429, 500, 502, 503, 504}
        last_error = "Unknown HTTP failure"
        for attempt in range(self.retries + 1):
            self._pace(host)
            req = request.Request(url, data=data, headers=request_headers, method=method)
            try:
                with request.urlopen(req, timeout=self.timeout) as response:
                    raw = response.read(self.max_bytes + 1)
                    if len(raw) > self.max_bytes:
                        return FetchResult(url, response.geturl(), response.status, error="Page exceeded size limit")
                    charset = response.headers.get_content_charset() or "utf-8"
                    body = raw.decode(charset, errors="replace")
                    return FetchResult(
                        url=url,
                        final_url=response.geturl(),
                        status=response.status,
                        body=body,
                        content_type=response.headers.get_content_type(),
                    )
            except error.HTTPError as exc:
                last_error = f"HTTP {exc.code}"
                if exc.code not in transient or attempt >= self.retries:
                    return FetchResult(url, exc.geturl(), exc.code, error=last_error)
                retry_after = exc.headers.get("Retry-After", "") if exc.headers else ""
                try:
                    pause = min(15.0, max(1.0, float(retry_after)))
                except ValueError:
                    pause = min(8.0, 2.0**attempt)
                time.sleep(pause)
            except (error.URLError, TimeoutError, OSError, ValueError) as exc:
                last_error = str(exc)
                if attempt >= self.retries:
                    return FetchResult(url, url, None, error=last_error)
                time.sleep(min(8.0, 2.0**attempt))
        return FetchResult(url, url, None, error=last_error)
