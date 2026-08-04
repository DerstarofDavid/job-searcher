"""SQLite history so daily runs can identify genuinely new opportunities."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import Evaluation, JobRecord
from .utils import utc_now_iso


SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    mode TEXT NOT NULL,
    provider TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    queries_run INTEGER NOT NULL DEFAULT 0,
    candidates_found INTEGER NOT NULL DEFAULT 0,
    pages_verified INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    fingerprint TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    last_scan_id INTEGER NOT NULL,
    last_score REAL NOT NULL,
    accepted INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    payload_json TEXT NOT NULL,
    evaluation_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_fingerprint ON jobs(fingerprint);
CREATE INDEX IF NOT EXISTS idx_jobs_last_seen ON jobs(last_seen);
CREATE TABLE IF NOT EXISTS observations (
    scan_id INTEGER NOT NULL,
    job_id INTEGER NOT NULL,
    seen_at TEXT NOT NULL,
    score REAL NOT NULL,
    accepted INTEGER NOT NULL,
    is_new INTEGER NOT NULL,
    PRIMARY KEY (scan_id, job_id)
);
"""


class JobStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def start_scan(self, mode: str, provider: str, started_at: str) -> int:
        cursor = self.connection.execute(
            "INSERT INTO scans(started_at, mode, provider) VALUES (?, ?, ?)",
            (started_at, mode, provider),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def upsert(self, scan_id: int, job: JobRecord, evaluation: Evaluation) -> bool:
        now = utc_now_iso()
        row = self.connection.execute(
            "SELECT id, url FROM jobs WHERE url = ? OR fingerprint = ? ORDER BY id LIMIT 1",
            (job.url, job.fingerprint),
        ).fetchone()
        payload = json.dumps(job.to_dict(), ensure_ascii=False)
        assessment = json.dumps(evaluation.to_dict(), ensure_ascii=False)
        is_new = row is None
        if row is None:
            cursor = self.connection.execute(
                """
                INSERT INTO jobs(
                    url, fingerprint, title, company, location, first_seen, last_seen,
                    last_scan_id, last_score, accepted, payload_json, evaluation_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.url,
                    job.fingerprint,
                    job.title,
                    job.company,
                    job.location,
                    now,
                    now,
                    scan_id,
                    evaluation.score,
                    int(evaluation.accepted),
                    payload,
                    assessment,
                ),
            )
            job_id = int(cursor.lastrowid)
        else:
            job_id = int(row["id"])
            self.connection.execute(
                """
                UPDATE jobs SET url=?, fingerprint=?, title=?, company=?, location=?,
                    last_seen=?, last_scan_id=?, last_score=?, accepted=?, active=1,
                    payload_json=?, evaluation_json=? WHERE id=?
                """,
                (
                    job.url,
                    job.fingerprint,
                    job.title,
                    job.company,
                    job.location,
                    now,
                    scan_id,
                    evaluation.score,
                    int(evaluation.accepted),
                    payload,
                    assessment,
                    job_id,
                ),
            )
        self.connection.execute(
            """
            INSERT OR REPLACE INTO observations(scan_id, job_id, seen_at, score, accepted, is_new)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (scan_id, job_id, now, evaluation.score, int(evaluation.accepted), int(is_new)),
        )
        self.connection.commit()
        return is_new

    def finish_scan(
        self,
        scan_id: int,
        *,
        queries_run: int,
        candidates_found: int,
        pages_verified: int,
        error: str | None = None,
    ) -> None:
        self.connection.execute(
            """
            UPDATE scans SET completed_at=?, status=?, queries_run=?, candidates_found=?,
                pages_verified=?, error=? WHERE id=?
            """,
            (
                utc_now_iso(),
                "failed" if error else "completed",
                queries_run,
                candidates_found,
                pages_verified,
                error,
                scan_id,
            ),
        )
        self.connection.commit()

    def stats(self) -> dict[str, int | str | None]:
        jobs = self.connection.execute("SELECT COUNT(*) AS count FROM jobs").fetchone()["count"]
        scans = self.connection.execute("SELECT COUNT(*) AS count FROM scans").fetchone()["count"]
        latest = self.connection.execute("SELECT completed_at FROM scans ORDER BY id DESC LIMIT 1").fetchone()
        return {"jobs": jobs, "scans": scans, "latest_scan": latest["completed_at"] if latest else None}

