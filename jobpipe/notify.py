"""Step 3: send each user one daily digest with their best new matches."""
from __future__ import annotations

import html
import logging
import time

from . import config, db
from .match import matches_for
from .models import Job, User
from .telegram_api import BotBlocked, Telegram, TelegramError

log = logging.getLogger("jobpipe.notify")

SOURCE_LABELS = {"greenhouse": "company site", "lever": "company site", "ashby": "company site",
                 "adzuna": "Adzuna", "jobspy:indeed": "Indeed", "jobspy:linkedin": "LinkedIn",
                 "jobspy:naukri": "Naukri", "jobspy:glassdoor": "Glassdoor"}


def exp_label(job: Job) -> str:
    if job.exp_min is None:
        return ""
    if job.exp_max is None:
        return f"{job.exp_min}+ yrs"
    return f"{job.exp_min} to {job.exp_max} yrs"


def format_job(n: int, job: Job) -> str:
    bits = [f"🏢 {html.escape(job.company)}"]
    if job.location:
        bits.append(f"📍 {html.escape(job.location[:60])}")
    if exp_label(job):
        bits.append(f"🧭 {exp_label(job)}")
    src = SOURCE_LABELS.get(job.source, job.source)
    return (f"<b>{n}. {html.escape(job.title[:100])}</b>\n" + "  ·  ".join(bits) +
            f"\n<a href=\"{html.escape(job.url, quote=True)}\">Apply here</a> <i>via {html.escape(src)}</i>")


def build_digest(user: User, jobs: list[Job], when: str = "today") -> tuple[str, list]:
    header = f"🔔 <b>{len(jobs)} new {html.escape(user.role_label or 'job')} {'match' if len(jobs) == 1 else 'matches'}</b> for you {when}\n"
    blocks = [format_job(i + 1, j) for i, j in enumerate(jobs)]
    footer = "\n<i>Tap 👎 on the ones that miss so I learn. /settings to tweak.</i>"
    # Telegram caps messages at 4096 chars, drop from the end if needed.
    while blocks and len(header + "\n\n".join(blocks) + footer) > 4000:
        blocks.pop()
    jobs = jobs[:len(blocks)]
    text = header + "\n" + "\n\n".join(blocks) + "\n" + footer
    buttons = [{"text": f"👎 {i + 1}", "callback_data": f"fb:{j.uid}:-1"} for i, j in enumerate(jobs)]
    keyboard = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
    return text, keyboard


def run(tg: Telegram | None = None, dry_run: bool = False, when: str = "today") -> dict:
    users = db.active_users()
    jobs = db.recent_jobs()
    report = {"users": len(users), "pool": len(jobs), "notified": 0, "jobs_sent": 0, "blocked": 0, "errors": 0}
    if not dry_run:
        tg = tg or Telegram()
    for user in users:
        picked = matches_for(user, jobs, db.sent_uids(user.chat_id), config.MAX_JOBS_PER_USER,
                             db.disliked_companies(user.chat_id))
        if not picked:
            continue
        text, keyboard = build_digest(user, picked, when)
        if dry_run:
            print(f"\n===== {user.chat_id} ({user.role_label}) =====\n{text}")
            report["notified"] += 1
            report["jobs_sent"] += len(picked)
            continue
        try:
            tg.send(user.chat_id, text, keyboard)
            db.mark_sent(user.chat_id, [j.uid for j in picked])
            report["notified"] += 1
            report["jobs_sent"] += len(picked)
        except BotBlocked:
            db.update_user(user.chat_id, active=False)
            report["blocked"] += 1
        except TelegramError as exc:
            log.warning("send to %s failed: %s", user.chat_id, exc)
            report["errors"] += 1
        time.sleep(0.05)  # stay well under Telegram's ~30 msg/sec
    return report
