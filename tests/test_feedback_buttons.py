"""The buttons under a digest: every tap says what happened."""
from jobpipe import bot, db
from jobpipe.models import Job
from jobpipe.normalize import finalize

from test_bot_and_pipeline import CHAT, cb, msg, signup


def _seed(companies):
    db.insert_jobs([finalize(Job(source="greenhouse", title="Data Analyst", company=c,
                                 location="Bengaluru, India", url=f"https://x/{c}")) for c in companies])


def _digest(tg):
    _seed(["Acme", "Globex", "Initech"])
    tg.sent.clear()
    bot.handle_update(tg, msg("/jobs"))
    d = tg.last
    assert "<a href=" in d["text"] and [b["text"] for b in d["keyboard"][0]] == ["👍 Good matches", "👎 A job doesn't fit"]
    return d


def _answer(tg):
    return [c for c in tg.calls if c[0] == "answer"][-1]


def _keyboard(tg):
    return [c for c in tg.calls if c[0] == "edit_keyboard"][-1][3]


def _company_at(d, n):
    line = [l for l in d["text"].split("\n") if l.startswith(f"<b>{n}.")][0]
    nxt = d["text"].split("\n")[d["text"].split("\n").index(line) + 1]
    return nxt.split("🏢 ")[1].split("  ·")[0]


def test_full_flow_pick_job_then_reason(tg):
    signup(tg)
    d = _digest(tg)
    mid = d["message_id"]

    bot.handle_update(tg, cb("dg:off", mid=mid))
    nums = [b["text"] for row in _keyboard(tg) for b in row]
    assert nums == ["#1", "#2", "#3", "↩ Back"]

    bot.handle_update(tg, cb("dg:pick:1", mid=mid))
    labels = [b["text"] for row in _keyboard(tg) for b in row]
    second = _company_at(d, 2)
    assert "🎯 Not my role" in labels and "🧭 Wrong experience level" in labels and "📍 Wrong city" in labels
    assert f"🚫 Hide all {second} jobs" in labels
    assert "#2" in _answer(tg)[2]

    bot.handle_update(tg, cb("dg:why:1:exp", mid=mid))
    text, alert = _answer(tg)[2], _answer(tg)[3]
    assert alert and "wrong level" in text and "Fresher" in text and "/settings" in text
    assert _keyboard(tg)[0][1]["callback_data"] == "dg:off"  # back to normal buttons


def test_hide_company_works_immediately_and_undo(tg):
    signup(tg)
    d = _digest(tg)
    first = _company_at(d, 1)
    bot.handle_update(tg, cb("dg:why:0:co", mid=d["message_id"]))
    assert "won't get jobs from " + first in _answer(tg)[2]
    assert first.lower() in db.disliked_companies(str(CHAT))
    undo = _keyboard(tg)[1][0]
    assert undo["text"].startswith("↩ Undo") and first in undo["text"]

    bot.handle_update(tg, msg("/me"))
    assert "Hidden companies" in tg.last["text"] and first in tg.last["text"]

    bot.handle_update(tg, cb(undo["callback_data"], mid=d["message_id"]))
    assert "can show up again" in _answer(tg)[2]
    assert first.lower() not in db.disliked_companies(str(CHAT))


def test_hidden_company_never_sent_again(tg):
    signup(tg)
    d = _digest(tg)
    first = _company_at(d, 1)
    bot.handle_update(tg, cb("dg:why:0:co", mid=d["message_id"]))
    db.insert_jobs([finalize(Job(source="lever", title="Junior Data Analyst", company=first,
                                 location="Bengaluru", url="https://x/new"))])
    bot.handle_update(tg, msg("/jobs"))
    assert first not in tg.last["text"]


def test_good_and_old_message(tg):
    signup(tg)
    d = _digest(tg)
    bot.handle_update(tg, cb("dg:good", mid=d["message_id"]))
    assert "Thanks" in _answer(tg)[2] and db.stats()["thumbs_up"] == 3
    bot.handle_update(tg, cb("dg:off", mid=99999))
    assert "too old" in _answer(tg)[2]


def test_unhide_command_and_stop_clears_everything(tg):
    signup(tg)
    db.hide_company(str(CHAT), "Acme")
    bot.handle_update(tg, msg("/unhide"))
    assert "Acme" in tg.last["text"]
    bot.handle_update(tg, msg("/unhide acme"))
    assert db.hidden_companies(str(CHAT)) == []
    db.hide_company(str(CHAT), "Acme")
    bot.handle_update(tg, msg("/stop"))
    assert db.hidden_companies(str(CHAT)) == []


def test_every_button_fits_telegram_limit(tg):
    long = "A Very Long Company Name Private Limited India"
    kb = bot._reason_keyboard(9, long) + bot._picker_keyboard(10)
    assert all(len(b["callback_data"].encode()) <= 64 for row in kb for b in row)
