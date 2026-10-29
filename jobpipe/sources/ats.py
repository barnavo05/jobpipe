"""Company career boards via public ATS APIs (Greenhouse, Lever, Ashby)."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ..models import Job
from ..normalize import finalize, is_india, remote_open_to_india
from . import SourceError, get_json

log = logging.getLogger("jobpipe.ats")

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
LEVER_URL = "https://api.lever.co/v0/postings/{slug}"
ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


# ---------------------------------------------------------------- parsers (pure, unit-tested)

def parse_greenhouse(data: dict, company: str) -> list[Job]:
    out = []
    for j in data.get("jobs", []):
        out.append(Job(
            source="greenhouse", title=j.get("title", ""), company=company,
            location=(j.get("location") or {}).get("name", ""),
            url=j.get("absolute_url", ""), description=j.get("content", ""),
            posted_at=j.get("first_published") or j.get("updated_at"),
        ))
    return out


def parse_lever(data: list, company: str) -> list[Job]:
    out = []
    for j in data or []:
        cats = j.get("categories") or {}
        locs = cats.get("allLocations") or [cats.get("location") or ""]
        created = j.get("createdAt")
        posted = datetime.fromtimestamp(created / 1000, tz=timezone.utc).isoformat() if created else None
        out.append(Job(
            source="lever", title=j.get("text", ""), company=company,
            location=" / ".join(l for l in locs if l),
            url=j.get("hostedUrl", ""),
            description=(j.get("descriptionPlain") or "") + "\n" + (j.get("additionalPlain") or ""),
            is_remote=(j.get("workplaceType") == "remote"), posted_at=posted,
        ))
    return out


def parse_ashby(data: dict, company: str) -> list[Job]:
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location") or ""] + [s.get("location", "") for s in j.get("secondaryLocations") or []]
        out.append(Job(
            source="ashby", title=j.get("title", ""), company=company,
            location=" / ".join(l for l in locs if l),
            url=j.get("jobUrl") or j.get("applyUrl", ""),
            description=j.get("descriptionPlain") or j.get("descriptionHtml", ""),
            is_remote=bool(j.get("isRemote")), posted_at=j.get("publishedAt"),
        ))
    return out


# ---------------------------------------------------------------- fetchers

def fetch_board(ats: str, slug: str, company: str) -> list[Job]:
    if ats == "greenhouse":
        return parse_greenhouse(get_json(GREENHOUSE_URL.format(slug=slug), {"content": "true"}), company)
    if ats == "lever":
        return parse_lever(get_json(LEVER_URL.format(slug=slug), {"mode": "json"}), company)
    if ats == "ashby":
        return parse_ashby(get_json(ASHBY_URL.format(slug=slug), {"includeCompensation": "false"}), company)
    raise ValueError(f"unknown ATS {ats}")


def load_companies(path: Path) -> list[tuple[str, str, str]]:
    """Returns (ats, slug, display name) triples from companies.yaml."""
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    out = []
    for ats in ("greenhouse", "lever", "ashby"):
        for entry in data.get(ats) or []:
            if isinstance(entry, str):
                out.append((ats, entry, entry.replace("-", " ").title()))
            elif entry.get("slug"):
                out.append((ats, entry["slug"], entry.get("name") or entry["slug"].title()))
    return out


def india_relevant(job: Job) -> bool:
    return is_india(job.location) or (job.is_remote and remote_open_to_india(job.location))


def fetch_all(companies: list[tuple[str, str, str]], workers: int = 8) -> tuple[list[Job], dict]:
    jobs: list[Job] = []
    stats = {"boards_ok": 0, "boards_failed": [], "raw": 0}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_board, ats, slug, name): (ats, slug) for ats, slug, name in companies}
        for fut in as_completed(futures):
            ats, slug = futures[fut]
            try:
                board = fut.result()
            except (SourceError, Exception) as exc:
                log.warning("board %s/%s failed: %s", ats, slug, exc)
                stats["boards_failed"].append(f"{ats}/{slug}")
                continue
            stats["boards_ok"] += 1
            stats["raw"] += len(board)
            for job in board:
                job = finalize(job)
                if india_relevant(job):
                    jobs.append(job)
    return jobs, stats
