"""Extract JobPosting JSON-LD and sensible fallbacks from public pages."""

from __future__ import annotations

import json
import re
from datetime import date
from html.parser import HTMLParser
from typing import Any, Iterable
from urllib.parse import urljoin

from .models import FetchResult, JobRecord, SearchHit
from .utils import (
    canonicalize_url,
    collapse_whitespace,
    domain_of,
    fold_text,
    make_fingerprint,
    parse_date,
    parse_workload,
    strip_html,
)


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.json_ld: list[str] = []
        self.meta: dict[str, str] = {}
        self.canonical = ""
        self.page_title = ""
        self.language = ""
        self._capture_script = False
        self._capture_title = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.casefold(): value or "" for key, value in attrs}
        if tag == "html":
            self.language = attributes.get("lang", "")
        elif tag == "script" and "ld+json" in attributes.get("type", "").casefold():
            self._capture_script, self._parts = True, []
        elif tag == "title":
            self._capture_title, self._parts = True, []
        elif tag == "meta":
            key = attributes.get("property") or attributes.get("name")
            content = attributes.get("content", "")
            if key and content:
                self.meta[key.casefold()] = content
        elif tag == "link" and "canonical" in attributes.get("rel", "").casefold():
            self.canonical = attributes.get("href", "")

    def handle_data(self, data: str) -> None:
        if self._capture_script or self._capture_title:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._capture_script:
            self.json_ld.append("".join(self._parts).strip())
            self._capture_script = False
        elif tag == "title" and self._capture_title:
            self.page_title = collapse_whitespace(" ".join(self._parts))
            self._capture_title = False


def _walk(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _job_postings(parser: _PageParser) -> list[dict[str, Any]]:
    postings: list[dict[str, Any]] = []
    for block in parser.json_ld:
        cleaned = re.sub(r"^\s*<!--|-->\s*$", "", block).strip()
        try:
            data = json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            continue
        for item in _walk(data):
            item_type = item.get("@type", "")
            types = item_type if isinstance(item_type, list) else [item_type]
            if any(str(value).casefold() == "jobposting" for value in types):
                postings.append(item)
    return postings


def _organization_name(value: Any) -> str:
    if isinstance(value, dict):
        return collapse_whitespace(str(value.get("name", "")))
    return collapse_whitespace(str(value or ""))


def _address(value: Any) -> str:
    if not isinstance(value, dict):
        return collapse_whitespace(str(value or ""))
    address = value.get("address", value)
    if isinstance(address, str):
        return collapse_whitespace(address)
    if not isinstance(address, dict):
        return ""
    parts = [
        address.get("addressLocality"),
        address.get("addressRegion"),
        address.get("postalCode"),
        address.get("addressCountry"),
    ]
    return collapse_whitespace(", ".join(str(item) for item in parts if item))


def _locations(posting: dict[str, Any]) -> str:
    raw = posting.get("jobLocation", [])
    items = raw if isinstance(raw, list) else [raw]
    values = [value for value in (_address(item) for item in items) if value]
    applicant = posting.get("applicantLocationRequirements")
    applicant_items = applicant if isinstance(applicant, list) else [applicant] if applicant else []
    for item in applicant_items:
        if isinstance(item, dict):
            name = collapse_whitespace(str(item.get("name", "")))
            if name:
                values.append(name)
    if fold_text(str(posting.get("jobLocationType", ""))) == "telecommute":
        values.append("Remote")
    return " / ".join(dict.fromkeys(values))


def _employment_type(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(collapse_whitespace(str(item)) for item in value)
    return collapse_whitespace(str(value or ""))


def _portal_stripped_parts(title: str) -> list[str]:
    parts = [collapse_whitespace(part) for part in re.split(r"\s+[|–—]\s+", title) if part.strip()]
    portals = {"linkedin", "indeed", "indeed com", "jobs ch", "jobscout24", "ostjob", "join"}
    while parts and fold_text(parts[-1]).replace(".", " ") in portals:
        parts.pop()
    return parts


def _fallback_company(title: str, snippet: str, parser: _PageParser) -> str:
    site = parser.meta.get("og:site_name", "")
    if site and fold_text(site) not in {"linkedin", "indeed", "jobs ch", "jobscout24"}:
        return collapse_whitespace(site)
    linkedin = re.match(r"^(.+?)\s+hiring\s+(.+?)\s+in\s+.+$", title, flags=re.IGNORECASE)
    if linkedin:
        return collapse_whitespace(linkedin.group(1))
    at_company = re.search(r"\s+(?:at|bei)\s+([^|–—]+)", title, flags=re.IGNORECASE)
    if at_company:
        return collapse_whitespace(at_company.group(1))
    snippet_company = re.search(
        r"(?:company|unternehmen|arbeitgeber)\s*:\s*([^|.;]{2,80})",
        snippet,
        flags=re.IGNORECASE,
    )
    if snippet_company:
        return collapse_whitespace(snippet_company.group(1))
    parts = _portal_stripped_parts(title)
    if len(parts) >= 2 and not re.search(r"\b(switzerland|schweiz|zurich|zürich|st\.? gallen|bern|basel)\b", parts[-1], re.IGNORECASE):
        return parts[-1]
    return "Unknown company"


def _fallback_title(hit: SearchHit, parser: _PageParser) -> str:
    value = parser.meta.get("og:title") or parser.page_title or hit.title
    linkedin = re.match(r"^(.+?)\s+hiring\s+(.+?)\s+in\s+.+$", value, flags=re.IGNORECASE)
    if linkedin:
        return collapse_whitespace(linkedin.group(2))
    parts = _portal_stripped_parts(value)
    return parts[0] if parts else collapse_whitespace(value) or "Untitled job"


def extract_job(hit: SearchHit, fetched: FetchResult | None) -> JobRecord:
    parser = _PageParser()
    full_text = ""
    verified = bool(fetched and not fetched.error and fetched.status and fetched.status < 400 and fetched.body)
    if verified and fetched:
        try:
            parser.feed(fetched.body)
        except Exception:
            verified = False
        full_text = strip_html(fetched.body)

    postings = _job_postings(parser) if verified else []
    posting = postings[0] if postings else {}
    title = collapse_whitespace(str(posting.get("title", ""))) or _fallback_title(hit, parser)
    description = strip_html(str(posting.get("description", ""))) or full_text
    company = _organization_name(posting.get("hiringOrganization")) or _fallback_company(hit.title, hit.snippet, parser)
    location = _locations(posting)
    employment = _employment_type(posting.get("employmentType"))
    page_url = fetched.final_url if fetched and fetched.final_url else hit.url
    if parser.canonical:
        page_url = urljoin(page_url, parser.canonical)
    page_url = canonicalize_url(page_url)
    workload_min, workload_max = parse_workload(" ".join((title, employment, description, hit.snippet)))
    posted = posting.get("datePosted") or hit.published_hint
    valid = posting.get("validThrough")
    posted_date, valid_date = parse_date(posted), parse_date(valid)
    closed_phrases = (
        "no longer accepting applications",
        "position has been filled",
        "job is no longer available",
        "vacancy is closed",
        "stelle ist nicht mehr verfugbar",
        "bewerbungsfrist abgelaufen",
    )
    closed = bool(valid_date and valid_date < date.today()) or any(
        phrase in fold_text(full_text[:20_000]) for phrase in closed_phrases
    )
    method = "json-ld JobPosting" if posting else "page metadata/text" if verified else "search snippet only"
    record = JobRecord(
        title=title,
        company=company,
        location=location or "Location not stated",
        url=page_url,
        source=hit.source or domain_of(page_url),
        description=description[:80_000],
        employment_type=employment,
        workload_min=workload_min,
        workload_max=workload_max,
        date_posted=posted_date.isoformat() if posted_date else None,
        valid_through=valid_date.isoformat() if valid_date else None,
        language=parser.language,
        verified=verified,
        extraction_method=method,
        search_query=hit.query,
        search_snippet=hit.snippet,
        closed=closed,
    )
    record.fingerprint = make_fingerprint(record.company, record.title, record.location)
    return record
