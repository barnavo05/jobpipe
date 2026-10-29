"""Telegram bot: signup flow, settings, feedback. Pure update handler + polling runner.

handle_update() is used by both:
  * polling (python -m jobpipe bot --once) on GitHub Actions or your laptop
  * the optional instant webhook (api/telegram.py on Vercel)
"""
from __future__ import annotations

import html
import json
import logging
import re
import time

from . import config, db
from .models import User
from .normalize import CITIES
from .roles import EXPERIENCE_BUCKETS, ROLES
from .telegram_api import BotBlocked, Telegram, TelegramError

log = logging.getLogger("jobpipe.bot")

LOCATION_CHOICES = ["bengaluru", "hyderabad", "pune", "mumbai", "delhi_ncr", "chennai",
                    "kolkata", "ahmedabad", "india", "remote"]
LOCATION_LABELS = {k: CITIES[k][0] for k in CITIES} | {"india": "Anywhere in India", "remote": "Remote"}

HELP = (
    "Here's what I can do:\n\n"
    "/me  see your current alert settings\n"
    "/settings  change role, experience or cities\n"
    "/exclude intern, sales  hide titles with these words\n"
    "/pause  stop alerts for a while\n"
    "/resume  turn alerts back on\n"
    "/stop  delete all your data\n\n"
    "Alerts land once a day. Tap 👎 on jobs that miss and I'll learn."
)


# ---------------------------------------------------------------- keyboards

def role_keyboard() -> list:
    buttons = [{"text": label, "callback_data": f"role:{key}"} for key, (label, _, _) in ROLES.items()]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([{"text": "✍️ Type my own role", "callback_data": "role:custom"}])
    return rows


def exp_keyboard() -> list:
    return [[{"text": label, "callback_data": f"exp:{key}"}] for key, (label, _, _) in EXPERIENCE_BUCKETS.items()]


def loc_keyboard(selected: list[str]) -> list:
    buttons = [{"text": ("✅ " if k in selected else "") + LOCATION_LABELS[k], "callback_data": f"loc:{k}"}
               for k in LOCATION_CHOICES]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([{"text": "Done ➡️", "callback_data": "loc:done"}])
    return rows


# ---------------------------------------------------------------- text helpers

def describe(user: User) -> str:
    exp = "any"
    for label, lo, hi in EXPERIENCE_BUCKETS.values():
        if (lo, hi) == (user.exp_min, user.exp_max):
            exp = label
    locs = ", ".join(LOCATION_LABELS.get(l, l) for l in user.locations) or "not set"
    lines = [
        f"<b>Role:</b> {html.escape(user.role_label or 'not set')}",
        f"<b>Experience:</b> {exp}",
        f"<b>Where:</b> {html.escape(locs)}",
    ]
    if user.exclude:
        lines.append(f"<b>Hiding:</b> {html.escape(', '.join(user.exclude))}")
    lines.append(f"<b>Alerts:</b> {'on ✅' if user.active else 'paused ⏸'}")
    return "\n".join(lines)


def profile_complete(user: User) -> bool:
    return bool((user.role_key or user.keywords) and user.exp_min is not None and user.locations)


# ---------------------------------------------------------------- flow

def ask_role(tg: Telegram, user: User, first_time: bool) -> None:
    name = html.escape(user.name or "there")
    intro = (f"Hey {name} 👋\n\nI scan company career pages and job portals every day and ping you "
             "only when something fits. Takes 20 seconds to set up.\n\n" if first_time else "")
    db.update_user(user.chat_id, state="awaiting_role")
    tg.send(user.chat_id, intro + "<b>What role are you looking for?</b>", role_keyboard())


def ask_exp(tg: Telegram, chat_id: str, label: str) -> None:
    db.update_user(chat_id, state="awaiting_exp")
    tg.send(chat_id, f"Nice, <b>{html.escape(label)}</b>.\n\nHow much experience do you have?", exp_keyboard())


def ask_loc(tg: Telegram, chat_id: str) -> None:
    db.update_user(chat_id, state="awaiting_loc", locations=[])
    tg.send(chat_id, "Where do you want to work? Pick as many as you like, then hit Done.", loc_keyboard([]))


def finish(tg: Telegram, user: User) -> None:
    user = db.update_user(user.chat_id, state="ready", active=True)
    tg.send(user.chat_id, "You're all set 🎉\n\n" + describe(user) +
            "\n\nYour first alerts come with the next daily run. /help shows everything else.")


def handle_message(tg: Telegram, msg: dict) -> None:
    chat = msg.get("chat") or {}
    if chat.get("type") != "private":
        return  # only 1:1 chats
    chat_id = str(chat["id"])
    text = (msg.get("text") or "").strip()
    name = (msg.get("from") or {}).get("first_name", "")
    user = db.get_user(chat_id)
    is_new = user is None
    user = user or db.ensure_user(chat_id, name)
    cmd = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""
    arg = text[len(text.split()[0]):].strip() if cmd else ""

    if cmd == "/start":
        if profile_complete(user) and not is_new:
            tg.send(chat_id, "Welcome back! Here's your setup:\n\n" + describe(user) + "\n\nUse /settings to change it.")
        else:
            ask_role(tg, user, first_time=True)
    elif cmd == "/settings":
        ask_role(tg, user, first_time=False)
    elif cmd == "/me":
        tg.send(chat_id, describe(user) if profile_complete(user) else "No setup yet. Send /start.")
    elif cmd == "/pause":
        db.update_user(chat_id, active=False)
        tg.send(chat_id, "Paused ⏸ No alerts until you send /resume.")
    elif cmd == "/resume":
        if profile_complete(user):
            db.update_user(chat_id, active=True)
            tg.send(chat_id, "Back on ✅ You'll get the next daily batch.")
        else:
            ask_role(tg, user, first_time=False)
    elif cmd == "/stop":
        db.delete_user(chat_id)
        tg.send(chat_id, "Done. All your data is deleted. Send /start anytime to come back 👋")
    elif cmd == "/exclude":
        if not arg:
            current = ", ".join(user.exclude) or "nothing"
            tg.send(chat_id, f"Currently hiding: {html.escape(current)}\n\nExample: /exclude intern, sales, java\n"
                             "Clear it with /exclude clear")
        elif arg.lower() == "clear":
            db.update_user(chat_id, exclude=[])
            tg.send(chat_id, "Cleared. Showing everything again.")
        else:
            words = [w.strip() for w in re.split(r"[,\n]", arg) if w.strip()][:15]
            db.update_user(chat_id, exclude=words)
            tg.send(chat_id, f"Got it, I'll hide titles with: {html.escape(', '.join(words))}")
    elif cmd == "/help":
        tg.send(chat_id, HELP)
    elif cmd == "/stats" and config.ADMIN_CHAT_ID and chat_id == str(config.ADMIN_CHAT_ID):
        total, active = db.count_users()
        tg.send(chat_id, f"👥 {total} users, {active} active")
    elif user.state == "awaiting_custom_role" and text and not cmd:
        label = text[:60]
        keywords = [p.strip() for p in label.split(",") if p.strip()][:3]
        db.update_user(chat_id, role_key=None, role_label=label, keywords=keywords)
        ask_exp(tg, chat_id, label)
    elif is_new or user.state == "new":
        ask_role(tg, user, first_time=True)
    else:
        tg.send(chat_id, "I didn't catch that. Tap a button above, or send /help.")


def handle_callback(tg: Telegram, cb: dict) -> None:
    msg = cb.get("message") or {}
    chat_id = str((msg.get("chat") or {}).get("id") or (cb.get("from") or {}).get("id"))
    message_id = msg.get("message_id")
    data = cb.get("data") or ""
    kind, _, value = data.partition(":")
    user = db.get_user(chat_id) or db.ensure_user(chat_id, (cb.get("from") or {}).get("first_name", ""))
    toast = ""

    if kind == "role":
        if value == "custom":
            db.update_user(chat_id, state="awaiting_custom_role")
            tg.send(chat_id, "Type the role you want, like <i>Prompt Engineer</i> or <i>SAP FICO</i>.\n"
                             "You can add up to 3, comma separated.")
        elif value in ROLES:
            label = ROLES[value][0]
            db.update_user(chat_id, role_key=value, role_label=label, keywords=[])
            ask_exp(tg, chat_id, label)
        if message_id:
            tg.edit_keyboard(chat_id, message_id, None)
    elif kind == "exp" and value in EXPERIENCE_BUCKETS:
        _, lo, hi = EXPERIENCE_BUCKETS[value]
        db.update_user(chat_id, exp_min=lo, exp_max=hi)
        if message_id:
            tg.edit_keyboard(chat_id, message_id, None)
        ask_loc(tg, chat_id)
    elif kind == "loc":
        if value == "done":
            if not user.locations:
                toast = "Pick at least one 🙂"
            else:
                if message_id:
                    tg.edit_keyboard(chat_id, message_id, None)
                finish(tg, user)
        elif value in LOCATION_LABELS:
            locs = list(user.locations)
            locs.remove(value) if value in locs else locs.append(value)
            db.update_user(chat_id, locations=locs)
            if message_id:
                tg.edit_keyboard(chat_id, message_id, loc_keyboard(locs))
    elif kind == "fb":
        uid, _, val = value.partition(":")
        db.set_feedback(chat_id, uid, -1 if val == "-1" else 1)
        toast = "Got it, fewer like that 👍" if val == "-1" else "Noted 👍"

    if cb.get("id"):
        tg.answer_callback(cb["id"], toast)


def handle_update(tg: Telegram, update: dict) -> None:
    try:
        if "callback_query" in update:
            handle_callback(tg, update["callback_query"])
        elif "message" in update:
            handle_message(tg, update["message"])
    except BotBlocked:
        log.info("user blocked the bot during update %s", update.get("update_id"))
    except TelegramError as exc:
        log.warning("telegram error on update %s: %s", update.get("update_id"), exc)


# ---------------------------------------------------------------- polling runner

def set_commands(tg: Telegram) -> None:
    tg.call("setMyCommands", commands=json.dumps([
        {"command": "start", "description": "Set up job alerts"},
        {"command": "me", "description": "See your settings"},
        {"command": "settings", "description": "Change role, experience, cities"},
        {"command": "exclude", "description": "Hide titles with certain words"},
        {"command": "pause", "description": "Pause alerts"},
        {"command": "resume", "description": "Resume alerts"},
        {"command": "stop", "description": "Delete my data"},
        {"command": "help", "description": "Help"},
    ]))


def poll(once: bool = False, tg: Telegram | None = None) -> int:
    """Process pending updates. once=True drains the queue and exits (for cron)."""
    tg = tg or Telegram()
    handled = 0
    offset = int(db.kv_get("tg_offset", "0") or 0) or None
    while True:
        updates = tg.get_updates(offset, timeout=0 if once else 25)
        for upd in updates:
            handle_update(tg, upd)
            handled += 1
            offset = upd["update_id"] + 1
            db.kv_set("tg_offset", str(offset))
        if once and not updates:
            break
        if not updates:
            time.sleep(0.5)
    return handled
