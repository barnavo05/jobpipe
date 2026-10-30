"""Minimal Telegram Bot API client (free, no limits that matter at our scale)."""
from __future__ import annotations

import json
import logging
import re
import time

import requests

from . import config

log = logging.getLogger("jobpipe.telegram")


def redact(text: str) -> str:
    """The bot token is part of every request URL, so network errors can echo it.
    Strip it (and anything token shaped) before a message reaches any log."""
    text = str(text)
    if config.TELEGRAM_BOT_TOKEN:
        text = text.replace(config.TELEGRAM_BOT_TOKEN, "<token>")
    return re.sub(r"\d{6,12}:[A-Za-z0-9_-]{30,}", "<token>", text)


class TelegramError(Exception):
    def __init__(self, msg=""):
        super().__init__(redact(msg))


class BotBlocked(TelegramError):
    """User blocked the bot or deleted their account: deactivate them."""


class Telegram:
    def __init__(self, token: str | None = None):
        self.token = token or config.TELEGRAM_BOT_TOKEN
        if not self.token:
            raise TelegramError("TELEGRAM_BOT_TOKEN is not set")
        self.base = f"https://api.telegram.org/bot{self.token}/"

    def call(self, method: str, _http_timeout: int = 40, **params):
        payload = {k: v for k, v in params.items() if v is not None}
        for k in ("reply_markup",):
            if k in payload and not isinstance(payload[k], str):
                payload[k] = json.dumps(payload[k])
        for attempt in range(4):
            try:
                resp = requests.post(self.base + method, data=payload, timeout=_http_timeout)
                data = resp.json()
            except Exception as exc:
                if attempt == 3:
                    raise TelegramError(f"{method}: {exc}") from None
                time.sleep(2 * (attempt + 1))
                continue
            if data.get("ok"):
                return data.get("result")
            code = data.get("error_code")
            desc = data.get("description", "")
            if code == 429:
                wait = (data.get("parameters") or {}).get("retry_after", 5)
                log.info("rate limited, sleeping %ss", wait)
                time.sleep(wait + 1)
                continue
            if code == 403 or "chat not found" in desc.lower():
                raise BotBlocked(desc)
            if code == 400 and "message is not modified" in desc.lower():
                return None
            raise TelegramError(f"{method} failed: {code} {desc}")
        raise TelegramError(f"{method}: gave up after retries")

    # convenience wrappers
    def send(self, chat_id, text: str, keyboard: list | None = None):
        return self.call("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML",
                         disable_web_page_preview="true",
                         reply_markup={"inline_keyboard": keyboard} if keyboard else None)

    def edit(self, chat_id, message_id, text: str, keyboard: list | None = None):
        return self.call("editMessageText", chat_id=chat_id, message_id=message_id, text=text,
                         parse_mode="HTML", disable_web_page_preview="true",
                         reply_markup={"inline_keyboard": keyboard} if keyboard else None)

    def edit_keyboard(self, chat_id, message_id, keyboard: list | None):
        return self.call("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id,
                         reply_markup={"inline_keyboard": keyboard or []})

    def answer_callback(self, callback_id: str, text: str = ""):
        return self.call("answerCallbackQuery", callback_query_id=callback_id, text=text or None)

    def get_updates(self, offset: int | None, timeout: int = 0):
        return self.call("getUpdates", _http_timeout=timeout + 15, offset=offset, timeout=timeout,
                         allowed_updates=json.dumps(["message", "callback_query"])) or []
