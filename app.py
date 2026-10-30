"""Vercel app: instant Telegram replies + the reliable digest timers (morning and evening).

/api/telegram    Telegram webhook (instant replies)
/api/cron/daily  hit by Vercel's timers (vercel.json); sends each digest once (morning, evening)

Vercel finds this file on its own (a top-level `app` in app.py) and routes every
request here. Telegram POSTs each new message to /api/telegram; we check it really
came from Telegram, handle it, and answer 200.

Without this deployed, the bot answers whenever the GitHub Actions bot workflow runs
(every ~10 min). Setup: README.md, Step 7. Vercel needs the env vars TELEGRAM_BOT_TOKEN,
DATABASE_URL and SUPABASE_POOLER_HOST.

Plain WSGI, so no web framework to install.
"""
from __future__ import annotations

import hmac
import json
import os

from jobpipe import bot, config, db, digest
from jobpipe.telegram_api import Telegram

WEBHOOK_PATH = "/api/telegram"
CRON_PATH = "/api/cron/daily"
# Without CRON_SECRET, digests can only be triggered inside these IST hours.
DIGEST_HOURS_IST = set(range(7, 12)) | set(range(17, 21))
_db_ready = False


def _respond(start_response, status: str, body: bytes = b"ok"):
    start_response(status, [("Content-Type", "text/plain"), ("Content-Length", str(len(body)))])
    return [body]


def _ensure_db():
    global _db_ready
    if not _db_ready:
        db.init_db()
        _db_ready = True


def _cron_allowed(environ) -> bool:
    """Vercel sends `Authorization: Bearer $CRON_SECRET` when that env var is set.
    Without it, only allow the digest windows: each digest runs once anyway,
    so the worst a stranger can do is trigger it a little early."""
    secret = os.environ.get("CRON_SECRET", "")
    if secret:
        return hmac.compare_digest(environ.get("HTTP_AUTHORIZATION") or "", f"Bearer {secret}")
    return digest.now_ist().hour in DIGEST_HOURS_IST


def cron_daily(environ, start_response):
    if not _cron_allowed(environ):
        return _respond(start_response, "403 Forbidden", b"outside the digest windows")
    try:
        _ensure_db()
        report = digest.run_once_today(tg=Telegram())
    except Exception as exc:
        print(f"cron error: {type(exc).__name__}: {exc}")
        return _respond(start_response, "500 Internal Server Error", b"digest failed, see logs")
    body = json.dumps(report, default=str).encode()
    print(f"cron daily: {body.decode()[:2000]}")
    return _respond(start_response, "200 OK", body)


def app(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET")
    path = (environ.get("PATH_INFO") or "/").rstrip("/") or "/"

    if method == "GET" and path == CRON_PATH:
        return cron_daily(environ, start_response)
    if method == "GET":
        return _respond(start_response, "200 OK", b"JobPipe webhook is alive")
    if method != "POST" or path != WEBHOOK_PATH:
        return _respond(start_response, "404 Not Found", b"not found")

    expected = config.TELEGRAM_WEBHOOK_SECRET
    got = environ.get("HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN") or ""
    if not expected or not hmac.compare_digest(got, expected):
        return _respond(start_response, "401 Unauthorized", b"unauthorized")

    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
        update = json.loads(environ["wsgi.input"].read(length) or b"{}")
        _ensure_db()
        bot.handle_update(Telegram(), update)
    except Exception as exc:  # always 200 so Telegram doesn't retry the same update forever
        print(f"webhook error: {type(exc).__name__}: {exc}")
    return _respond(start_response, "200 OK")
