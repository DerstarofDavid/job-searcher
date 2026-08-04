"""End-to-end discovery, verification, scoring, history, and reporting."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .config import AppConfig
from .demo import demo_items
from .extract import extract_job
from .models import Evaluation, FetchResult, JobRecord, ScanResult, SearchHit, SourceHealth
from .notifications import notify
from .report import write_reports
from .score import evaluate
from .search import build_queries, discover, make_providers
from .storage import JobStore
from .utils import canonicalize_url, domain_of, is_skipped_domain, utc_now_iso
from .webclient import WebClient


Progress = Callable[[str], None]


def _dedupe_hits(hits: list[SearchHit]) -> list[SearchHit]:
    selected: dict[str, SearchHit] = {}
    for hit in hits:
        key = canonicalize_url(hit.url)
        if not key.startswith(("http://", "https://")):
            continue
        current = selected.get(key)
        if current is None or len(hit.snippet) > len(current.snippet):
            hit.url = key
            selected[key] = hit
    return list(selected.values())


def _dedupe_jobs(
    values: list[tuple[JobRecord, Evaluation]]
) -> list[tuple[JobRecord, Evaluation]]:
    selected: dict[str, tuple[JobRecord, Evaluation]] = {}
    for job, assessment in values:
        unknown_company = job.company.casefold().startswith("unknown")
        key = job.url if unknown_company else job.fingerprint
        current = selected.get(key)
        if current is None:
            selected[key] = (job, assessment)
            continue
        old_job, old_assessment = current
        new_quality = (assessment.accepted, job.verified, assessment.score, len(job.description))
        old_quality = (old_assessment.accepted, old_job.verified, old_assessment.score, len(old_job.description))
        if new_quality > old_quality:
            selected[key] = (job, assessment)
    return list(selected.values())


def _client(config: AppConfig) -> WebClient:
    values = config.search
    return WebClient(
        user_agent=values["user_agent"],
        timeout=float(values.get("timeout_seconds", 18)),
        delay=float(values.get("request_delay_seconds", 1.2)),
        max_bytes=int(values.get("max_page_bytes", 2_500_000)),
        respect_robots=bool(values.get("respect_robots_txt", True)),
    )


def _process(
    items: list[tuple[SearchHit, FetchResult | None]], config: AppConfig, progress: Progress
) -> list[tuple[JobRecord, Evaluation]]:
    processed: list[tuple[JobRecord, Evaluation]] = []
    total = len(items)
    for index, (hit, fetched) in enumerate(items, start=1):
        progress(f"Evaluating {index}/{total}: {hit.title[:90]}")
        job = extract_job(hit, fetched)
        processed.append((job, evaluate(job, config.data)))
    return _dedupe_jobs(processed)


def run_scan(
    config: AppConfig,
    *,
    mode: str,
    provider_name: str,
    query_limit: int | None = None,
    send_notifications: bool = True,
    progress: Progress = print,
) -> ScanResult:
    started = utc_now_iso()
    store = JobStore(config.resolve_path(config.reports["database"]))
    scan_id = store.start_scan(mode, provider_name, started)
    queries_run = candidates_found = pages_verified = 0
    try:
        client = _client(config)
        queries = build_queries(config.search, mode)
        if query_limit is not None:
            queries = queries[: max(0, query_limit)]
        providers = make_providers(
            provider_name,
            client,
            int(config.search.get("max_results_per_query", 10)),
            int(config.search.get("tavily_auto_max_queries", 12)),
        )
        progress(f"Running {len(queries)} targeted queries with {', '.join(item.name for item in providers)}")
        raw_hits, source_health = discover(queries, providers, progress)
        queries_run = sum(item.queries for item in source_health)
        hits = _dedupe_hits(raw_hits)
        maximum = int(config.search.get("max_candidate_pages", 240))
        if len(hits) > maximum:
            progress(f"Candidate safety cap: evaluating the first {maximum} of {len(hits)} unique URLs")
            hits = hits[:maximum]
        candidates_found = len(hits)
        skipped = config.search.get("skip_direct_fetch_domains", [])
        items: list[tuple[SearchHit, FetchResult | None]] = []
        fetch_errors: list[str] = []
        for index, hit in enumerate(hits, start=1):
            domain = domain_of(hit.url)
            if is_skipped_domain(domain, skipped):
                items.append((hit, None))
                continue
            progress(f"Verifying page {index}/{len(hits)}: {domain}")
            fetched = client.fetch(hit.url)
            if fetched.error:
                message = f"{domain}: {fetched.error}"
                if message not in fetch_errors:
                    fetch_errors.append(message[:220])
            else:
                pages_verified += 1
            items.append((hit, fetched))
        source_health.append(
            SourceHealth(
                "public-page verification",
                queries=len(hits),
                hits=pages_verified,
                errors=fetch_errors[:12],
            )
        )
        evaluated = _process(items, config, progress)
        accepted: list[tuple[JobRecord, Evaluation, bool]] = []
        removed: list[tuple[JobRecord, Evaluation]] = []
        for job, assessment in evaluated:
            is_new = store.upsert(scan_id, job, assessment)
            if assessment.accepted:
                accepted.append((job, assessment, is_new))
            else:
                removed.append((job, assessment))
        accepted.sort(key=lambda item: (item[1].score, item[2], item[0].verified), reverse=True)
        removed.sort(key=lambda item: item[1].score, reverse=True)
        completed = utc_now_iso()
        result = ScanResult(
            scan_id=scan_id,
            started_at=started,
            completed_at=completed,
            mode=mode,
            provider=" + ".join(item.name for item in providers),
            jobs=accepted,
            removed=removed,
            source_health=source_health,
            queries_run=queries_run,
            candidates_found=candidates_found,
            pages_verified=pages_verified,
        )
        result.report_paths = write_reports(result, config.data, config.resolve_path(config.reports["directory"]))
        if send_notifications:
            for warning in notify(accepted, config.notifications):
                progress("Notification warning: " + warning)
        store.finish_scan(
            scan_id,
            queries_run=queries_run,
            candidates_found=candidates_found,
            pages_verified=pages_verified,
        )
        return result
    except Exception as exc:
        store.finish_scan(
            scan_id,
            queries_run=queries_run,
            candidates_found=candidates_found,
            pages_verified=pages_verified,
            error=str(exc),
        )
        raise
    finally:
        store.close()


def run_demo(config: AppConfig, progress: Progress = print) -> ScanResult:
    started = utc_now_iso()
    values = _process(demo_items(), config, progress)
    accepted = [(job, assessment, True) for job, assessment in values if assessment.accepted]
    removed = [(job, assessment) for job, assessment in values if not assessment.accepted]
    accepted.sort(key=lambda item: item[1].score, reverse=True)
    completed = utc_now_iso()
    result = ScanResult(
        scan_id=0,
        started_at=started,
        completed_at=completed,
        mode="offline demo",
        provider="bundled sample pages",
        jobs=accepted,
        removed=removed,
        source_health=[SourceHealth("offline sample", 5, 5, [])],
        queries_run=0,
        candidates_found=5,
        pages_verified=5,
    )
    demo_directory = config.resolve_path(config.reports["directory"]) / "demo"
    result.report_paths = write_reports(result, config.data, demo_directory)
    return result
