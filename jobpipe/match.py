"""Step 2: decide which jobs each user should hear about."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from .models import Job, User
from .normalize import detect_cities, is_india, remote_open_to_india
from .roles import title_matches

EXP_TOLERANCE = 1  # a fresher still sees "0-1 yrs"; a 2-yr person still sees "3+ yrs"


def experience_ok(job: Job, user: User) -> bool:
    if user.exp_min is None and user.exp_max is None:
        return True
    u_min = user.exp_min or 0
    u_max = user.exp_max if user.exp_max is not None else 40
    if job.exp_min is not None and job.exp_min > u_max + EXP_TOLERANCE:
        return False  # too senior
    if job.exp_max is not None and job.exp_max < u_min - EXP_TOLERANCE:
        return False  # too junior
    return True


def location_ok(job: Job, user: User) -> bool:
    locs = set(user.locations or ["india"])
    if job.is_remote and "remote" in locs and remote_open_to_india(job.location):
        return True
    if "india" in locs and is_india(job.location):
        return True
    return bool(detect_cities(job.location) & locs)


def excluded(job: Job, user: User, muted_companies: set[str] = frozenset()) -> bool:
    if job.company.lower() in muted_companies:
        return True
    text = job.title.lower()
    return any(re.search(r"(?<![a-z0-9])" + re.escape(w.lower()) + r"(?![a-z0-9])", text) for w in user.exclude)


def is_match(job: Job, user: User, muted_companies: set[str] = frozenset()) -> bool:
    return (
        title_matches(job.title, user.role_key, user.keywords)
        and experience_ok(job, user)
        and location_ok(job, user)
        and not excluded(job, user, muted_companies)
    )


def _age_days(job: Job) -> float:
    for stamp in (job.posted_at, job.fetched_at):
        if not stamp:
            continue
        try:
            dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400)
        except ValueError:
            continue
    return 7.0


def score(job: Job, user: User) -> float:
    s = 0.0
    if detect_cities(job.location) & set(user.locations):
        s += 2  # exact city they asked for
    if job.exp_min is not None:
        s += 1.5  # explicit experience match beats a guess
    if job.source in ("greenhouse", "lever", "ashby"):
        s += 1  # direct company posting, usually fresher and less spammy
    s += max(0.0, 3 - _age_days(job))  # newer is better
    return s


def matches_for(user: User, jobs: list[Job], already_sent: set[str], limit: int,
                muted_companies: set[str] = frozenset()) -> list[Job]:
    picked = [j for j in jobs if j.uid not in already_sent and is_match(j, user, muted_companies)]
    picked.sort(key=lambda j: score(j, user), reverse=True)
    return diversify(picked, limit)


def _family(job: Job) -> str:
    return "company site" if job.source in ("greenhouse", "lever", "ashby") else job.source


def diversify(ranked: list[Job], limit: int) -> list[Job]:
    """Round robin across sources (LinkedIn, Naukri, Indeed, company sites...) so one
    portal can't fill the whole digest. Within each source, best score first."""
    buckets: dict[str, list[Job]] = {}
    for j in ranked:
        buckets.setdefault(_family(j), []).append(j)
    out: list[Job] = []
    while len(out) < limit and any(buckets.values()):
        for fam in list(buckets):
            if buckets[fam] and len(out) < limit:
                out.append(buckets[fam].pop(0))
    return out
