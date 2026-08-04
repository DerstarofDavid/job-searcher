"""Offline sample pages for validating extraction, ranking, and exclusions."""

from __future__ import annotations

import re
from datetime import date, timedelta

from .models import FetchResult, SearchHit


PAGES = [
    (
        SearchHit(
            "Working Student Finance Automation | Alpine Foods",
            "https://example.test/jobs/finance-automation",
            "English working-student opening in Zurich, 40-60%.",
            "offline-demo",
            "demo finance automation",
            1,
        ),
        """<!doctype html><html lang="en"><head><title>Working Student Finance Automation | Alpine Foods</title>
        <script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting","title":"Working Student Finance Automation","description":"Join our finance transformation team. You will document requirements, improve processes, test business tools, work with stakeholders and learn on the job. Familiarity with ERP, finance, Git and REST API is useful. German B2 and fluent English.","hiringOrganization":{"@type":"Organization","name":"Alpine Foods AG"},"jobLocation":{"address":{"addressLocality":"Zürich","addressCountry":"CH"}},"employmentType":"PART_TIME 40-60%","datePosted":"2026-08-01","validThrough":"2026-09-15"}</script></head><body><h1>Working Student Finance Automation</h1></body></html>""",
    ),
    (
        SearchHit(
            "Junior Business Central Application Consultant – St. Gallen",
            "https://example.test/jobs/bc-consultant",
            "Junior ERP role at 60% with training.",
            "offline-demo",
            "demo business central",
            2,
        ),
        """<!doctype html><html lang="en"><head><title>Junior Business Central Application Consultant</title>
        <script type="application/ld+json">{"@type":"JobPosting","title":"Junior Microsoft Dynamics 365 Business Central Application Consultant","description":"Entry-level role supporting ERP implementations. You clarify requirements, handle tickets, test and document AL extensions. Training is provided. Business Central, AL, Azure DevOps and PowerShell are advantageous.","hiringOrganization":{"name":"Eastern Process Systems AG"},"jobLocation":{"address":{"addressLocality":"St. Gallen","addressCountry":"CH"}},"employmentType":"PART_TIME 60%","datePosted":"2026-07-28","validThrough":"2026-10-01"}</script></head><body>Junior role</body></html>""",
    ),
    (
        SearchHit(
            "Senior ERP Consultant | Open Systems Boutique",
            "https://example.test/jobs/senior-erp",
            "Senior-titled role with flexible workload and no fixed years requirement.",
            "offline-demo",
            "demo senior",
            3,
        ),
        """<!doctype html><html lang="en"><head><script type="application/ld+json">{"@type":"JobPosting","title":"Senior ERP Consultant","description":"We value practical ERP support, requirements gathering, stakeholder communication, documentation and motivation to learn. Business Central experience is welcome. No fixed tenure requirement; scope follows capability.","hiringOrganization":{"name":"Open Systems Boutique AG"},"jobLocation":{"address":{"addressLocality":"Winterthur","addressCountry":"CH"}},"employmentType":"PART_TIME 40-60%","datePosted":"2026-07-30"}</script></head><body>Senior ERP Consultant</body></html>""",
    ),
    (
        SearchHit("IT Business Analyst | EY", "https://example.test/jobs/ey", "40-60% Zurich", "offline-demo", "demo applied", 4),
        """<html lang="en"><head><script type="application/ld+json">{"@type":"JobPosting","title":"Working Student IT Business Analyst","description":"Junior business analyst and process improvement role.","hiringOrganization":{"name":"EY"},"jobLocation":{"address":{"addressLocality":"Zürich","addressCountry":"CH"}},"employmentType":"40-60%","datePosted":"2026-08-01"}</script></head><body>EY role</body></html>""",
    ),
    (
        SearchHit("ERP Project Manager | Faraway Tech", "https://example.test/jobs/fulltime", "Full-time role in Bern", "offline-demo", "demo reject", 5),
        """<html lang="de"><head><script type="application/ld+json">{"@type":"JobPosting","title":"ERP Project Manager","description":"Vollzeit 100%. Mindestens 5 Jahre Berufserfahrung und Deutsch C1 erforderlich.","hiringOrganization":{"name":"Faraway Tech AG"},"jobLocation":{"address":{"addressLocality":"Bern","addressCountry":"CH"}},"employmentType":"FULL_TIME 100%","datePosted":"2026-07-20"}</script></head><body>ERP Project Manager</body></html>""",
    ),
]


def demo_items() -> list[tuple[SearchHit, FetchResult]]:
    today = date.today()
    values: list[tuple[SearchHit, FetchResult]] = []
    for index, (hit, body) in enumerate(PAGES):
        posted = (today - timedelta(days=index + 1)).isoformat()
        valid = (today + timedelta(days=45)).isoformat()
        body = re.sub(r'"datePosted":"[^"]+"', f'"datePosted":"{posted}"', body)
        body = re.sub(r'"validThrough":"[^"]+"', f'"validThrough":"{valid}"', body)
        values.append((hit, FetchResult(hit.url, hit.url, 200, body, "text/html")))
    return values
