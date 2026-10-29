"""Adzuna India search API. Free key: https://developer.adzuna.com (sign up, copy app_id + app_key)."""
from __future__ import annotations

import logging

from .. import config
from ..models import Job
from ..normalize import finalize
from . import get_json

log = logging.getLogger("jobpipe.adzuna")

URL = "https://api.adzuna.com/v1/api/jobs/in/search/{page}"


def parse(data: dict) -> list[Job]:
    out = []
    for r in data.get("results", []):
        out.append(Job(
            source="adzuna", title=r.get("title", ""),
            company=(r.get("company") or {}).get("display_name", ""),
            location=(r.get("location") or {}).get("display_name", ""),
            url=r.get("redirect_url", ""), description=r.get("description", ""),
            posted_at=r.get("created"),
        ))
    return out


def enabled() -> bool:
    return bool(config.ADZUNA_APP_ID and config.ADZUNA_APP_KEY)


def search(term: str, location: str | None, pages: int = 1) -> list[Job]:
    if not enabled():
        return []
    jobs: list[Job] = []
    for page in range(1, pages + 1):
        params = {
            "app_id": config.ADZUNA_APP_ID, "app_key": config.ADZUNA_APP_KEY,
            "what": term, "results_per_page": 50, "max_days_old": max(1, config.HOURS_OLD // 24),
            "sort_by": "date", "content-type": "application/json",
        }
        if location and location.lower() not in ("india", "remote"):
            params["where"] = location
        if location and location.lower() == "remote":
            params["what"] = f"{term} remote"
        batch = parse(get_json(URL.format(page=page), params))
        jobs.extend(finalize(j) for j in batch)
        if len(batch) < 50:
            break
    return jobs
