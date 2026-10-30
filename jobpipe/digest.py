"""The morning digest, sent at most once per day (India time) however many times it's triggered.

Vercel's free timers fire reliably but may fire twice, and we keep a couple of backup
timers in case one is missed. A one-time slot per date in the database makes all of
that safe: the first trigger of the day sends, every later one just says "already done".
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


def slot_key(day: str | None = None) -> str:
    return f"digest:{day or now_ist().date().isoformat()}"


def claim_today() -> bool:
    return db.kv_claim(slot_key(), utcnow_iso())


def run_once_today(tg=None, use_jobspy: bool = False) -> dict:
    day = now_ist().date().isoformat()
    if not db.kv_claim(slot_key(day), utcnow_iso()):
        return {"date": day, "skipped": "digest already sent today"}
    report: dict = {"date": day}
    try:
        # Freshen the pool first. A failure here must not cost anyone their digest:
        # jobs collected earlier (GitHub runs) are still there.
        try:
            report["collect"] = collect.run(use_jobspy=use_jobspy)
        except Exception as exc:
            log.warning("collect failed, sending from the existing pool: %s", exc)
            report["collect"] = {"error": f"{type(exc).__name__}: {exc}"}
        report["notify"] = notify.run(tg=tg)
    except Exception:
        db.kv_delete(slot_key(day))  # let a backup timer try again
        raise
    return report
