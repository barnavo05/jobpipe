"""OPTIONAL instant-reply mode: Telegram webhook as a free Vercel serverless function.

Without this, the bot answers whenever the GitHub Actions bot workflow runs (every ~10 min).
With this deployed, replies are instant. Setup steps are in README.md (Step 7). Needs the env vars
TELEGRAM_BOT_TOKEN, DATABASE_URL and SUPABASE_POOLER_HOST on Vercel.
"""
import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jobpipe import bot, config, db  # noqa: E402
from jobpipe.telegram_api import Telegram  # noqa: E402

_ready = False


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        global _ready
        expected = config.TELEGRAM_WEBHOOK_SECRET
        got = self.headers.get("X-Telegram-Bot-Api-Secret-Token") or ""
        if not expected or not hmac.compare_digest(got, expected):
            self.send_response(401)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            update = json.loads(self.rfile.read(length) or b"{}")
            if not _ready:
                db.init_db()
                _ready = True
            bot.handle_update(Telegram(), update)
        except Exception as exc:  # always 200 so Telegram doesn't retry forever
            print(f"webhook error: {exc}")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"JobPipe webhook is alive")
