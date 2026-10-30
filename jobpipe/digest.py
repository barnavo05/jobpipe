"""Digests go out twice a day (India time): morning (~8 AM) and evening (~6 PM).

Each one is sent at most once, however many times it's triggered. Vercel's free timers
fire reliably but may fire twice, and we keep backup timers in case one is missed.
A one-time slot per date + period in the database makes all of that safe: the first
trigger sends, every later one just says "already done".
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from . import collect, db, notify
from .models import utcnow_iso

log = logging.getLogger("jobpipe.digest")

IST = timezone(timedelta(hours=5, minutes=30))  # India has no daylight saving


def now_ist() -> datetime:
    return datetime.now(IST)


def period(now: datetime | None = None) -> str:
    """'am' before 3 PM IST, 'pm' after."""
    return "am" if (now or now_ist()).hour < 15 else "pm"


def slot_key(day: str | None = None, when: str | None = None) -> str:
    now = now_ist()
    day = day or now.date().isoformat()
    when = when or period(now)
    return f"digest:{day}" if when == "am" else f"digest:{day}:{when}"


def claim_today() -> bool:
    """Take the current slot (used by manual full runs so a timer won't double-send)."""
    return db.kv_claim(slot_key(), utcnow_iso())


def run_once_today(tg=None, use_jobspy: bool = False) -> dict:
    now = now_ist()
    day, when = now.date().isoformat(), period(now)
    key = slot_key(day, when)
    if not db.kv_claim(key, utcnow_iso()):
        return {"date": day, "period": when, "skipped": "digest already sent"}
    report: dict = {"date": day, "period": when}
    try:
        # Freshen the pool first. A failure here must not cost anyone their digest:
        # jobs collected earlier (GitHub runs) are still there.
        try:
            report["collect"] = collect.run(use_jobspy=use_jobspy)
        except Exception as exc:
            log.warning("collect failed, sending from the existing pool: %s", exc)
            report["collect"] = {"error": f"{type(exc).__name__}: {exc}"}
        report["notify"] = notify.run(tg=tg, when="this evening" if when == "pm" else "today")
    except Exception:
        db.kv_delete(key)  # let a backup timer try again
        raise
    return report
