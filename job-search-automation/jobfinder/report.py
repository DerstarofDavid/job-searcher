"""Human-readable Markdown/HTML reports plus machine-readable JSON."""

from __future__ import annotations

import json
from dataclasses import asdict
from html import escape
from pathlib import Path

from .models import Evaluation, JobRecord, ScanResult


def _workload(job: JobRecord) -> str:
    if job.workload_min is None:
        return "Not stated"
    if job.workload_min == job.workload_max:
        return f"{job.workload_min}%"
    return f"{job.workload_min}–{job.workload_max}%"


def _top(scan: ScanResult, limit: int, minimum: float) -> list[tuple[JobRecord, Evaluation, bool]]:
    values = [item for item in scan.jobs if item[1].score >= minimum]
    return sorted(values, key=lambda item: (item[1].score, item[2], item[0].verified), reverse=True)[:limit]


def _low(scan: ScanResult, low: float, high: float, limit: int) -> list[tuple[JobRecord, Evaluation, bool]]:
    values = [item for item in scan.jobs if low <= item[1].score <= high]
    return sorted(values, key=lambda item: item[1].score, reverse=True)[:limit]


def _watch(scan: ScanResult, minimum: float, limit: int) -> list[tuple[JobRecord, Evaluation, bool]]:
    values = [item for item in scan.jobs if 4.0 <= item[1].score < minimum]
    return sorted(values, key=lambda item: (item[1].score, item[2]), reverse=True)[:limit]


def _markdown(scan: ScanResult, config: dict) -> str:
    ranking = config["ranking"]
    top = _top(scan, int(ranking["top_results"]), float(ranking["minimum_top_score"]))
    watch = _watch(scan, float(ranking["minimum_top_score"]), int(ranking.get("watch_result_limit", 15)))
    low = _low(
        scan,
        float(ranking["low_priority_min_score"]),
        float(ranking["low_priority_max_score"]),
        int(ranking["low_priority_result_limit"]),
    )
    lines = [
        "# David’s Swiss job-search report",
        "",
        f"Run completed: {scan.completed_at}  ",
        f"Mode: **{scan.mode}** · Providers: **{scan.provider}**  ",
        f"Coverage: {scan.queries_run} queries · {scan.candidates_found} unique candidates · {scan.pages_verified} pages verified",
        "",
        "## Top ranked opportunities",
        "",
    ]
    if not top:
        lines.extend(["No verified candidate reached the configured 6/10 threshold in this run.", ""])
    for rank, (job, evaluation, is_new) in enumerate(top, start=1):
        new = " · **NEW**" if is_new else ""
        verification = "verified" if job.verified else "search result only"
        lines.extend(
            [
                f"### {rank}. {job.company} — {job.title} ({evaluation.score}/10){new}",
                "",
                f"- Location: {job.location}",
                f"- Workload: {_workload(job)}",
                f"- Evidence: {verification}; {job.extraction_method}",
                f"- Apply/check: [{job.url}]({job.url})",
                f"- Why you fit: {'; '.join(evaluation.reasons[:5]) or 'Potential adjacent fit'}",
                f"- Risk/gap: {'; '.join(evaluation.risks[:5]) or 'No material gap detected automatically'}",
                "",
            ]
        )
    lines.extend(["## Borderline opportunities (4–5.9/10)", ""])
    if watch:
        for job, evaluation, is_new in watch:
            new = " · NEW" if is_new else ""
            lines.append(
                f"- [{job.company} — {job.title}]({job.url}) ({evaluation.score}/10{new}): "
                + ("; ".join(evaluation.risks[:3]) or "lower overall evidence")
            )
    else:
        lines.append("None in this run.")
    lines.extend(["", "## 2–3/10 discoveries (names only)", ""])
    if low:
        for job, evaluation, _ in low:
            lines.append(f"- {job.company} — {job.title} ({evaluation.score}/10)")
    else:
        lines.append("None in this run.")
    lines.extend(["", "## Removed in this run", ""])
    if scan.removed:
        for job, evaluation in scan.removed[: int(config["reports"].get("include_removed_limit", 60))]:
            lines.append(f"- {job.company} — {job.title}: {evaluation.removal_reason}")
    else:
        lines.append("None.")
    lines.extend(["", "## Source health", ""])
    for status in scan.source_health:
        error = f" · errors: {' | '.join(status.errors)}" if status.errors else ""
        lines.append(f"- {status.source}: {status.queries} queries, {status.hits} raw hits{error}")
    lines.extend(
        [
            "",
            "> Automated rankings are a screening aid. Confirm workload, closing date, language, and application eligibility on the employer’s page before applying.",
            "",
        ]
    )
    return "\n".join(lines)


def _cards(top: list[tuple[JobRecord, Evaluation, bool]]) -> str:
    if not top:
        return '<div class="empty">No candidate reached 6/10 in this run.</div>'
    cards: list[str] = []
    for rank, (job, evaluation, is_new) in enumerate(top, start=1):
        badges = [f'<span class="score">{evaluation.score}/10</span>']
        if is_new:
            badges.append('<span class="new">NEW</span>')
        badges.append('<span class="verified">Verified</span>' if job.verified else '<span class="unverified">Needs verification</span>')
        reasons = "".join(f"<li>{escape(item)}</li>" for item in evaluation.reasons[:5]) or "<li>Potential adjacent fit</li>"
        risks = "".join(f"<li>{escape(item)}</li>" for item in evaluation.risks[:5]) or "<li>No material gap detected automatically</li>"
        cards.append(
            f"""
            <article class="job">
              <div class="rank">{rank}</div>
              <div class="body">
                <div class="badges">{''.join(badges)}</div>
                <h3>{escape(job.title)}</h3>
                <div class="company">{escape(job.company)}</div>
                <div class="facts"><span>📍 {escape(job.location)}</span><span>⏱ {_workload(job)}</span></div>
                <div class="columns"><div><h4>Why it fits</h4><ul>{reasons}</ul></div><div><h4>Risk / gap</h4><ul>{risks}</ul></div></div>
                <a class="button" href="{escape(job.url, quote=True)}" target="_blank" rel="noopener">Open application</a>
              </div>
            </article>"""
        )
    return "".join(cards)


def _html(scan: ScanResult, config: dict) -> str:
    ranking = config["ranking"]
    top = _top(scan, int(ranking["top_results"]), float(ranking["minimum_top_score"]))
    watch = _watch(scan, float(ranking["minimum_top_score"]), int(ranking.get("watch_result_limit", 15)))
    low = _low(scan, float(ranking["low_priority_min_score"]), float(ranking["low_priority_max_score"]), int(ranking["low_priority_result_limit"]))
    low_items = "".join(f"<li>{escape(job.company)} — {escape(job.title)} ({evaluation.score}/10)</li>" for job, evaluation, _ in low) or "<li>None in this run.</li>"
    watch_items = "".join(
        f'<li><a href="{escape(job.url, quote=True)}" target="_blank" rel="noopener">{escape(job.company)} — {escape(job.title)}</a> ({evaluation.score}/10): {escape("; ".join(evaluation.risks[:3]) or "lower overall evidence")}</li>'
        for job, evaluation, _ in watch
    ) or "<li>None in this run.</li>"
    removed = "".join(
        f"<li><strong>{escape(job.company)} — {escape(job.title)}</strong>: {escape(evaluation.removal_reason or '')}</li>"
        for job, evaluation in scan.removed[: int(config["reports"].get("include_removed_limit", 60))]
    ) or "<li>None.</li>"
    health = "".join(
        f"<tr><td>{escape(item.source)}</td><td>{item.queries}</td><td>{item.hits}</td><td>{escape(' | '.join(item.errors) or 'OK')}</td></tr>"
        for item in scan.source_health
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>David's job search — {escape(scan.completed_at)}</title>
<style>
:root{{--ink:#14213d;--muted:#5b6475;--blue:#2457d6;--bg:#f3f6fb;--card:#fff;--green:#087f5b;--amber:#9a6700;--line:#dce3ef}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1050px;margin:auto;padding:34px 18px 70px}}header{{background:linear-gradient(135deg,#14213d,#2457d6);color:white;border-radius:18px;padding:28px;box-shadow:0 12px 30px #183c8c22}}
h1{{margin:0 0 8px;font-size:30px}}header p{{margin:4px 0;opacity:.9}}h2{{margin:34px 0 14px}}.job{{display:grid;grid-template-columns:48px 1fr;background:var(--card);border:1px solid var(--line);border-radius:16px;margin:14px 0;box-shadow:0 6px 18px #14213d0c;overflow:hidden}}
.rank{{background:#e9efff;color:var(--blue);font-size:23px;font-weight:800;text-align:center;padding-top:25px}}.body{{padding:22px}}h3{{font-size:21px;margin:8px 0 2px}}.company{{font-weight:650;color:var(--muted)}}.badges span{{display:inline-block;border-radius:99px;padding:3px 9px;font-size:12px;font-weight:750;margin-right:5px}}.score,.new{{background:#dff7ec;color:var(--green)}}.verified{{background:#e7efff;color:var(--blue)}}.unverified{{background:#fff0cf;color:var(--amber)}}
.facts{{display:flex;gap:24px;flex-wrap:wrap;margin:15px 0;color:var(--muted)}}.columns{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}h4{{margin:6px 0}}ul{{margin:5px 0 14px;padding-left:21px}}.button{{display:inline-block;background:var(--blue);color:white;text-decoration:none;border-radius:9px;padding:9px 14px;font-weight:700}}.panel{{background:white;border:1px solid var(--line);border-radius:14px;padding:18px;margin:12px 0}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:9px;border-bottom:1px solid var(--line)}}.note{{color:var(--muted);font-size:13px;margin-top:28px}}
@media(max-width:700px){{.columns{{grid-template-columns:1fr}}.job{{grid-template-columns:36px 1fr}}.rank{{font-size:18px}}}}
</style></head><body><main>
<header><h1>David’s Swiss job search</h1><p>{escape(scan.completed_at)} · {escape(scan.mode)} scan · {escape(scan.provider)}</p><p>{scan.queries_run} queries · {scan.candidates_found} unique candidates · {scan.pages_verified} public pages verified</p></header>
<h2>Top ranked opportunities</h2>{_cards(top)}
<h2>Borderline opportunities (4–5.9/10)</h2><div class="panel"><ul>{watch_items}</ul></div>
<h2>2–3/10 discoveries (no links)</h2><div class="panel"><ul>{low_items}</ul></div>
<h2>Removed in this run</h2><div class="panel"><ul>{removed}</ul></div>
<h2>Source health</h2><div class="panel"><table><thead><tr><th>Source</th><th>Queries</th><th>Hits</th><th>Status</th></tr></thead><tbody>{health}</tbody></table></div>
<p class="note">Rankings are a screening aid. Confirm workload, closing date, language and eligibility on the employer page before applying.</p>
</main></body></html>"""


def write_reports(scan: ScanResult, config: dict, directory: Path) -> dict[str, str]:
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = scan.completed_at.replace(":", "-").replace("+", "_")
    markdown = _markdown(scan, config)
    html = _html(scan, config)
    payload = {
        "scan": {key: value for key, value in asdict(scan).items() if key not in {"jobs", "removed", "report_paths"}},
        "jobs": [
            {"job": job.to_dict(), "evaluation": evaluation.to_dict(), "is_new": is_new}
            for job, evaluation, is_new in scan.jobs
        ],
        "removed": [
            {"job": job.to_dict(), "evaluation": evaluation.to_dict()} for job, evaluation in scan.removed
        ],
    }
    paths = {
        "markdown": directory / f"job-report-{timestamp}.md",
        "html": directory / f"job-report-{timestamp}.html",
        "json": directory / f"job-report-{timestamp}.json",
        "latest_markdown": directory / "latest.md",
        "latest_html": directory / "latest.html",
        "latest_json": directory / "latest.json",
    }
    paths["markdown"].write_text(markdown, encoding="utf-8")
    paths["html"].write_text(html, encoding="utf-8")
    paths["json"].write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    paths["latest_markdown"].write_text(markdown, encoding="utf-8")
    paths["latest_html"].write_text(html, encoding="utf-8")
    paths["latest_json"].write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {key: str(value) for key, value in paths.items()}
