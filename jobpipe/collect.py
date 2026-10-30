"""Step 1 of the daily run: pull jobs from every source into the jobs table."""
from __future__ import annotations

import logging
from collections import Counter

from . import config, db
from .models import Job, User
from .normalize import CITIES, is_india
from .roles import search_term_for
from .sources import adzuna, ats, jobspy_source

log = logging.getLogger("jobpipe.collect")


def location_query(loc_key: str) -> str:
    if loc_key in CITIES:
        return CITIES[loc_key][2]
    if loc_key == "remote":
        return "remote"
    return "India"


def build_queries(users: list[User], limit: int) -> list[tuple[str, str]]:
    """The cost-saving trick: one search per distinct (role, city), not per user.

    Most popular combos first, so if we hit the cap the long tail is what gets dropped.
    """
    counts: Counter[tuple[str, str]] = Counter()
    for u in users:
        term = search_term_for(u.role_key, u.keywords)
        if not term:
            continue
        for loc in u.locations or ["india"]:
            counts[(term.lower(), location_query(loc))] += 1
    return [q for q, _ in counts.most_common(limit)]


def keep(job: Job) -> bool:
    return bool(job.title and job.url) and (is_india(job.location) or job.is_remote or not job.location)


def run(users: list[User] | None = None, use_jobspy: bool = True) -> dict:
    """use_jobspy=False = only the fast, official sources (company boards + Adzuna).
    That's what the Vercel morning run uses; GitHub adds LinkedIn/Indeed/Naukri."""
    users = users if users is not None else db.active_users()
    all_jobs: list[Job] = []
    report: dict = {}

    companies = ats.load_companies(config.COMPANIES_FILE)
    if companies:
        board_jobs, stats = ats.fetch_all(companies)
        all_jobs += board_jobs
        report["boards"] = {**stats, "kept": len(board_jobs)}
        log.info("boards: %s ok, %s failed, %s India-relevant jobs",
                 stats["boards_ok"], len(stats["boards_failed"]), len(board_jobs))

    queries = build_queries(users, config.MAX_SEARCH_QUERIES)
    report["queries"] = len(queries)
    search_counts: Counter[str] = Counter()
    for term, loc in queries:
        for source in ((adzuna, jobspy_source) if use_jobspy else (adzuna,)):
            try:
                found = [j for j in source.search(term, loc) if keep(j)]
            except Exception as exc:
                log.warning("%s failed for %r @ %s: %s", source.__name__, term, loc, exc)
                continue
            search_counts[source.__name__.rsplit(".", 1)[-1]] += len(found)
            all_jobs += found
        log.info("searched %r @ %s", term, loc)
    report["search"] = dict(search_counts)

    report["by_source"] = dict(Counter(j.source for j in all_jobs))
    report["new_jobs"] = db.insert_jobs(all_jobs)
    report["pruned"] = db.prune_jobs()
    log.info("collected %s jobs, %s new", len(all_jobs), report["new_jobs"])
    return report
