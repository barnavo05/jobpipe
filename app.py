"""OPTIONAL instant-reply mode: the Telegram webhook, served by Vercel for free.

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

from jobpipe import bot, config, db
from jobpipe.telegram_api import Telegram

WEBHOOK_PATH = "/api/telegram"
_db_ready = False


def _respond(start_response, status: str, body: bytes = b"ok"):
    start_response(status, [("Content-Type", "text/plain"), ("Content-Length", str(len(body)))])
    return [body]


def app(environ, start_response):
    global _db_ready
    method = environ.get("REQUEST_METHOD", "GET")
    path = (environ.get("PATH_INFO") or "/").rstrip("/") or "/"

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
        if not _db_ready:
            db.init_db()
            _db_ready = True
        bot.handle_update(Telegram(), update)
    except Exception as exc:  # always 200 so Telegram doesn't retry the same update forever
        print(f"webhook error: {type(exc).__name__}: {exc}")
    return _respond(start_response, "200 OK")
