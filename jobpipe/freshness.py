"""Fresh vs ghost jobs.

Every collection run records when each job was seen (db.job_history). That history is
kept much longer than the jobs themselves, so we can tell:

  * fresh:    posted in the last 48 hours AND we only started seeing it recently
              (an old job that was just edited has a new date but an old first_seen)
  * reposted: it vanished for 10+ days and came back, or its "posted" date jumped
              forward while it's still the same job (the usual LinkedIn bump)
  * stale:    it has been listed for 30+ days, so it may already be filled

The tags are shown in the alert and stale/reposted jobs rank a little lower.
Nothing is hidden: the user decides.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .models import Job

IST = timezone(timedelta(hours=5, minutes=30))

FRESH_HOURS = 48          # "posted" date at most this old
FRESH_SEEN_DAYS = 3       # and we first saw it at most this long ago
REPOST_GAP_DAYS = 10      # gone this long, then back = reposted
REPOST_BUMP_DAYS = 3      # "posted" date moved forward by this much = reposted
STALE_DAYS = 30           # listed this long = may be filled
COMPANY_SITE = {"greenhouse", "lever", "ashby"}


def parse_ts(value) -> tuple[datetime | None, bool]:
    """(UTC datetime, date_only). Sources give full timestamps, dates, or nothing."""
    if not value:
        return None, False
    s = str(value).strip()
    date_only = len(s) == 10
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None, False
    if date_only:  # a plain date from an Indian portal means that day in IST
        dt = dt.replace(tzinfo=IST)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc), date_only


def _iso(dt: datetime | None) -> str | None:
    return dt.replace(microsecond=0).isoformat() if dt else None


def next_history(row: dict | None, job: Job, now: datetime) -> dict:
    """The job_history row after seeing `job` again at `now`."""
    posted, _ = parse_ts(job.posted_at)
    if row is None:
        return {"uid": job.uid, "first_seen": _iso(now), "last_seen": _iso(now),
                "first_posted": _iso(posted), "last_posted": _iso(posted), "reposts": 0}
    out = dict(row)
    reposts = int(row.get("reposts") or 0)
    last_seen, _ = parse_ts(row.get("last_seen"))
    last_posted, _ = parse_ts(row.get("last_posted"))
    gap = last_seen is not None and (now - last_seen) >= timedelta(days=REPOST_GAP_DAYS)
    bump = posted is not None and last_posted is not None and (posted - last_posted) >= timedelta(days=REPOST_BUMP_DAYS)
    if gap or bump:
        reposts += 1
    out.update(last_seen=_iso(now), reposts=reposts)
    if posted is not None:
        out["last_posted"] = _iso(posted)
        if not row.get("first_posted"):
            out["first_posted"] = _iso(posted)
    return out


def listed_since(job: Job) -> datetime | None:
    """Earliest date we know this job existed."""
    dates = [d for d in (parse_ts(v)[0] for v in (job.first_posted, job.posted_at, job.first_seen)) if d]
    return min(dates) if dates else None


def is_fresh(job: Job, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    posted, _ = parse_ts(job.posted_at)
    seen, _ = parse_ts(job.first_seen or job.fetched_at)
    if posted is None or job.reposts:
        return False
    if now - posted > timedelta(hours=FRESH_HOURS):
        return False
    return seen is None or now - seen <= timedelta(days=FRESH_SEEN_DAYS)


def is_stale(job: Job, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    since = listed_since(job)
    return since is not None and now - since >= timedelta(days=STALE_DAYS)


def is_ghosty(job: Job, now: datetime | None = None) -> bool:
    return job.reposts >= 1 or is_stale(job, now)


def _ago(job: Job, now: datetime) -> str:
    posted, date_only = parse_ts(job.posted_at)
    if date_only:
        days = (now.astimezone(IST).date() - posted.astimezone(IST).date()).days
        return "today" if days <= 0 else "yesterday"
    hours = int((now - posted).total_seconds() // 3600)
    if hours < 1:
        return "just now"
    return f"{hours} hr{'s' if hours != 1 else ''} ago"


def tag(job: Job, now: datetime | None = None) -> str:
    """One short line for the alert, or "" when there's nothing worth saying."""
    now = now or datetime.now(timezone.utc)
    if job.reposts:
        times = "once" if job.reposts == 1 else f"{job.reposts}x"
        since = listed_since(job)
        when = f" since {since.astimezone(IST):%b} {since.astimezone(IST).day}" if since else ""
        return f"♻️ Reposted {times}{when}, may never close"
    if is_stale(job, now):
        since = listed_since(job).astimezone(IST)
        return f"⏳ Open since {since:%b} {since.day}, may be filled"
    if is_fresh(job, now):
        if job.source in COMPANY_SITE:
            return f"🆕 Posted {_ago(job, now)} on the company site. You're early"
        return f"🆕 Posted {_ago(job, now)}"
    return ""
