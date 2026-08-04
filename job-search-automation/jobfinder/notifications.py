"""Optional email and Telegram alerts, configured only through environment variables."""

from __future__ import annotations

import json
import os
import smtplib
from email.message import EmailMessage
from urllib import request

from .models import Evaluation, JobRecord


def _message(jobs: list[tuple[JobRecord, Evaluation, bool]]) -> str:
    lines = ["David's Job Finder found new high-fit openings:", ""]
    for job, evaluation, _ in jobs:
        lines.extend(
            [
                f"{job.company} — {job.title} ({evaluation.score}/10)",
                f"{job.location} · {job.workload_min or '?'}–{job.workload_max or '?'}%",
                job.url,
                "",
            ]
        )
    return "\n".join(lines).strip()


def send_email(subject: str, body: str) -> None:
    host = os.environ["JOBFINDER_SMTP_HOST"]
    port = int(os.environ.get("JOBFINDER_SMTP_PORT", "587"))
    sender = os.environ.get("JOBFINDER_SMTP_FROM") or os.environ["JOBFINDER_SMTP_USER"]
    recipient = os.environ["JOBFINDER_EMAIL_TO"]
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(body)
    with smtplib.SMTP(host, port, timeout=25) as smtp:
        if os.environ.get("JOBFINDER_SMTP_STARTTLS", "true").casefold() not in {"0", "false", "no"}:
            smtp.starttls()
        user = os.environ.get("JOBFINDER_SMTP_USER")
        password = os.environ.get("JOBFINDER_SMTP_PASSWORD")
        if user and password:
            smtp.login(user, password)
        smtp.send_message(message)


def send_telegram(body: str) -> None:
    token = os.environ["JOBFINDER_TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["JOBFINDER_TELEGRAM_CHAT_ID"]
    payload = json.dumps({"chat_id": chat_id, "text": body[:4000], "disable_web_page_preview": True}).encode("utf-8")
    req = request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=25) as response:
        if response.status >= 400:
            raise RuntimeError(f"Telegram returned HTTP {response.status}")


def notify(
    jobs: list[tuple[JobRecord, Evaluation, bool]], notification_config: dict
) -> list[str]:
    minimum = float(notification_config.get("minimum_score", 8.0))
    only_new = bool(notification_config.get("only_new_jobs", True))
    selected = [item for item in jobs if item[1].score >= minimum and (item[2] or not only_new)]
    if not selected:
        return []
    body = _message(selected)
    errors: list[str] = []
    if notification_config.get("email"):
        try:
            send_email(f"{len(selected)} new high-fit job opening(s)", body)
        except Exception as exc:
            errors.append(f"Email alert failed: {exc}")
    if notification_config.get("telegram"):
        try:
            send_telegram(body)
        except Exception as exc:
            errors.append(f"Telegram alert failed: {exc}")
    return errors
