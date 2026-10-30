"""Messages for the owner: /stats text and short run reports (needs ADMIN_CHAT_ID)."""
from __future__ import annotations

import logging

from . import config, db

log = logging.getLogger("jobpipe.admin")


def stats_text() -> str:
    s = db.stats()
    return (
        "<b>📊 JobPipe stats</b>\n\n"
        f"👥 Users: <b>{s['users']}</b> ({s['active_users']} active, +{s['new_users_7d']} this week)\n"
        f"🔎 Listings scanned (7 days): <b>{s['scanned_7d']:,}</b>\n"
        f"🆕 New jobs found (7 days): {s['new_jobs_7d']:,}\n"
        f"🗂 Jobs in pool now: {s['jobs_in_pool']:,}\n"
        f"📨 Jobs sent: {s['sent_24h']} today · {s['sent_7d']} this week · {s['sent_total']:,} all time\n"
        f"👎 Thumbs down: {s['thumbs_down']}"
    )


def digest_line(report: dict) -> str:
    """One readable line for a digest run report."""
    when = "Evening" if report.get("period") == "pm" else "Morning"
    if "skipped" in report:
        return ""
    n = report.get("notify", {}) or {}
    c = report.get("collect", {}) or {}
    line = (f"✅ {when} digest: sent {n.get('jobs_sent', 0)} jobs to {n.get('notified', 0)} "
            f"of {n.get('users', 0)} users")
    if c.get("new_jobs") is not None:
        line += f" · {c['new_jobs']} new jobs found"
    if n.get("blocked"):
        line += f" · {n['blocked']} blocked the bot"
    if n.get("errors") or "error" in c:
        line += " · ⚠️ some errors, check the logs"
    return line


def send(text: str) -> None:
    """Best effort: a report must never break a run."""
    if not (config.ADMIN_CHAT_ID and config.TELEGRAM_BOT_TOKEN and text):
        return
    try:
        from .telegram_api import Telegram
        Telegram().send(config.ADMIN_CHAT_ID, text)
    except Exception as exc:
        log.warning("admin message failed: %s", exc)
