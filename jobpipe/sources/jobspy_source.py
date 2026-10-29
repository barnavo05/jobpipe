"""Indeed / LinkedIn / Naukri via the open-source JobSpy library.

Heads up: these sites don't offer free APIs and actively block scrapers. Keep volume
low (few queries, ~30 results each) and treat failures as normal. Board sources and
Adzuna are the reliable backbone; this is a bonus layer.
"""
from __future__ import annotations

import logging
import math
import time

from .. import config
from ..models import Job
from ..normalize import finalize

log = logging.getLogger("jobpipe.jobspy")


def _val(row, key):
    v = row.get(key)
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return v


def parse_dataframe(df) -> list[Job]:
    out = []
    if df is None or len(df) == 0:
        return out
    for row in df.to_dict(orient="records"):
        posted = _val(row, "date_posted")
        desc = _val(row, "description") or ""
        exp_range = _val(row, "experience_range")  # Naukri gives e.g. "0-2 Yrs"
        if exp_range:
            desc = f"Experience: {exp_range}\n{desc}"
        out.append(Job(
            source=f"jobspy:{_val(row, 'site') or 'unknown'}",
            title=_val(row, "title") or "", company=_val(row, "company") or "",
            location=_val(row, "location") or "",
            url=_val(row, "job_url_direct") or _val(row, "job_url") or "",
            description=str(desc), is_remote=bool(_val(row, "is_remote")),
            posted_at=str(posted) if posted else None,
        ))
    return out


def search(term: str, location: str | None) -> list[Job]:
    if not config.JOBSPY_ENABLED:
        return []
    try:
        from jobspy import scrape_jobs
    except ImportError:
        log.warning("python-jobspy not installed, skipping")
        return []
    remote = (location or "").lower() == "remote"
    loc = "India" if remote or not location else f"{location}, India"
    jobs: list[Job] = []
    # One site per call so a block on LinkedIn doesn't kill Indeed results.
    for site in config.JOBSPY_SITES:
        try:
            df = scrape_jobs(
                site_name=[site], search_term=term,
                location=(location if site == "naukri" and location and not remote else loc),
                is_remote=remote, results_wanted=config.JOBSPY_RESULTS,
                hours_old=config.HOURS_OLD, country_indeed="India", verbose=0,
            )
            jobs.extend(finalize(j) for j in parse_dataframe(df))
        except Exception as exc:
            log.warning("jobspy %s failed for %r @ %s: %s", site, term, loc, exc)
        time.sleep(2)  # be polite
    return jobs
