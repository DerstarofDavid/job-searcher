"""Typed records shared by the job-finder pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class SearchHit:
    title: str
    url: str
    snippet: str = ""
    source: str = ""
    query: str = ""
    rank: int = 0
    published_hint: str | None = None


@dataclass(slots=True)
class FetchResult:
    url: str
    final_url: str
    status: int | None
    body: str = ""
    content_type: str = ""
    error: str | None = None
    robots_allowed: bool = True


@dataclass(slots=True)
class JobRecord:
    title: str
    company: str
    location: str
    url: str
    source: str
    description: str = ""
    employment_type: str = ""
    workload_min: int | None = None
    workload_max: int | None = None
    date_posted: str | None = None
    valid_through: str | None = None
    language: str = ""
    verified: bool = False
    extraction_method: str = "search-snippet"
    search_query: str = ""
    search_snippet: str = ""
    closed: bool = False
    fingerprint: str = ""

    def searchable_text(self) -> str:
        return " ".join(
            value
            for value in (
                self.title,
                self.company,
                self.location,
                self.description,
                self.employment_type,
                self.search_snippet,
            )
            if value
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Evaluation:
    score: float
    accepted: bool
    tier: str
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    matched_roles: list[str] = field(default_factory=list)
    matched_skills: list[str] = field(default_factory=list)
    removal_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SourceHealth:
    source: str
    queries: int = 0
    hits: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ScanResult:
    scan_id: int
    started_at: str
    completed_at: str
    mode: str
    provider: str
    jobs: list[tuple[JobRecord, Evaluation, bool]]
    removed: list[tuple[JobRecord, Evaluation]]
    source_health: list[SourceHealth]
    queries_run: int
    candidates_found: int
    pages_verified: int
    report_paths: dict[str, str] = field(default_factory=dict)

