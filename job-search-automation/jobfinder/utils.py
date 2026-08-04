"""Small dependency-free helpers."""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


TRACKING_PARAMETERS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "trk",
    "trackingid",
    "refid",
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored += 1
        elif tag in {"p", "div", "br", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._ignored:
            self._ignored -= 1
        elif tag in {"p", "div", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._ignored:
            self.parts.append(data)


def strip_html(value: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(value or "")
        value = " ".join(parser.parts)
    except Exception:
        value = re.sub(r"<[^>]+>", " ", value or "")
    return collapse_whitespace(html.unescape(value))


def collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def fold_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    return collapse_whitespace(value.casefold())


def normalize_company(value: str) -> str:
    value = fold_text(value)
    # Treat common Swiss/German ASCII transliterations as equivalent (Bär/Baer).
    value = value.replace("ae", "a").replace("oe", "o").replace("ue", "u")
    value = re.sub(
        r"\b(ag|gmbh|sa|se|ltd|limited|inc|group|holding|schweiz|switzerland)\b",
        " ",
        value,
    )
    return collapse_whitespace(re.sub(r"[^a-z0-9]+", " ", value))


def company_matches(candidate: str, listed: str) -> bool:
    left, right = normalize_company(candidate), normalize_company(listed)
    if not left or not right:
        return False
    if min(len(left), len(right)) <= 4:
        return left == right
    return left == right or left in right or right in left


def contains_phrase(text: str, phrase: str) -> bool:
    haystack, needle = fold_text(text), fold_text(phrase)
    if not needle:
        return False
    if len(needle) <= 3 and needle.isalnum():
        return bool(re.search(rf"\b{re.escape(needle)}\b", haystack))
    return needle in haystack


def canonicalize_url(value: str) -> str:
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return value.strip()
    if not parsed.scheme:
        return value.strip()
    query = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in TRACKING_PARAMETERS
        and not key.casefold().startswith("utm_")
    ]
    path = parsed.path.rstrip("/") or "/"
    return urlunparse(
        (
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            path,
            "",
            urlencode(query, doseq=True),
            "",
        )
    )


def domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.casefold().split(":", 1)[0]
    except ValueError:
        return ""


def is_skipped_domain(domain: str, skipped: list[str]) -> bool:
    domain = domain.casefold()
    return any(domain == item.casefold() or domain.endswith("." + item.casefold()) for item in skipped)


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def parse_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = collapse_whitespace(str(value))
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text[:30], fmt).date()
        except ValueError:
            continue
    return None


def parse_workload(text: str) -> tuple[int | None, int | None]:
    folded = fold_text(text)
    contexts = []
    for match in re.finditer(
        r"(pensum|workload|employment level|beschaftigungsgrad|part[- _]?time|teilzeit|working student|werkstudent)",
        folded,
    ):
        contexts.append(folded[max(0, match.start() - 50) : match.end() + 100])

    range_patterns = (
        r"(?<!\d)(\d{1,3})\s*[-–—/]\s*(\d{1,3})\s*%",
        r"(?<!\d)(\d{1,3})\s*(?:bis|to)\s*(\d{1,3})\s*%",
        r"(?<!\d)(\d{1,3})\s*%\s*(?:bis|to|[-–—/])\s*(\d{1,3})\s*%",
    )
    for context in [*contexts, folded]:
        for pattern in range_patterns:
            match = re.search(pattern, context, flags=re.IGNORECASE)
            if match:
                low, high = int(match.group(1)), int(match.group(2))
                if 1 <= low <= 100 and 1 <= high <= 100:
                    return min(low, high), max(low, high)

    for context in contexts:
        match = re.search(r"(?<!\d)(\d{1,3})\s*%", context)
        if match:
            value = int(match.group(1))
            if 1 <= value <= 100:
                return value, value

    if re.search(r"\b(full[- ]?time|vollzeit|100\s*(?:percent|prozent))\b", folded):
        return 100, 100
    return None, None


def make_fingerprint(company: str, title: str, location: str) -> str:
    raw = "|".join((normalize_company(company), fold_text(title), fold_text(location)))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def safe_filename(value: str) -> str:
    folded = fold_text(value)
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-") or "report"
