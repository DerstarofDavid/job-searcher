"""Configuration loading, validation, and local .env support."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "job_filter.json"


@dataclass(slots=True)
class AppConfig:
    data: dict[str, Any]
    path: Path
    root: Path

    @property
    def search(self) -> dict[str, Any]:
        return self.data["search"]

    @property
    def filter(self) -> dict[str, Any]:
        return self.data["filter"]

    @property
    def ranking(self) -> dict[str, Any]:
        return self.data["ranking"]

    @property
    def reports(self) -> dict[str, Any]:
        return self.data["reports"]

    @property
    def notifications(self) -> dict[str, Any]:
        return self.data["notifications"]

    def resolve_path(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else self.root / path

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_dotenv(path: Path | None = None) -> None:
    path = path or PROJECT_ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key, value = key.strip(), value.strip().strip("\"").strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_config(path: str | Path | None = None) -> AppConfig:
    chosen = Path(path).expanduser().resolve() if path else DEFAULT_CONFIG
    data = json.loads(chosen.read_text(encoding="utf-8"))
    required = {"candidate", "search", "filter", "ranking", "reports", "notifications"}
    missing = required.difference(data)
    if missing:
        raise ValueError(f"Configuration is missing sections: {', '.join(sorted(missing))}")
    root = chosen.parent.parent if chosen.parent.name == "config" else chosen.parent
    config = AppConfig(data=data, path=chosen, root=root)
    config.resolve_path(data["reports"]["directory"]).mkdir(parents=True, exist_ok=True)
    config.resolve_path(data["reports"]["database"]).parent.mkdir(parents=True, exist_ok=True)
    return config


def company_bucket(status: str) -> str:
    mapping = {
        "applied": "applied_waiting_companies",
        "waiting": "applied_waiting_companies",
        "rejected": "rejected_companies",
        "blocked": "blocked_companies",
    }
    try:
        return mapping[status.casefold()]
    except KeyError as exc:
        raise ValueError("Status must be applied, waiting, rejected, or blocked") from exc

