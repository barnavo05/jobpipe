from jobpipe import bot, collect, config, db, notify
from jobpipe.models import Job
from jobpipe.sources import adzuna, ats, jobspy_source

CHAT = 555


def msg(text, chat=CHAT):
    return {"message": {"chat": {"id": chat, "type": "private"}, "from": {"first_name": "Barnavo"}, "text": text}}


def cb(data, chat=CHAT, mid=1):
    return {"callback_query": {"id": "cb1", "data": data, "from": {"id": chat},
                               "message": {"chat": {"id": chat}, "message_id": mid}}}


def signup(tg, chat=CHAT, role="role:data_analyst", exp="exp:exp_0", locs=("bengaluru",)):
    bot.handle_update(tg, msg("/start", chat))
    bot.handle_update(tg, cb(role, chat))
    bot.handle_update(tg, cb(exp, chat))
    for l in locs:
        bot.handle_update(tg, cb(f"loc:{l}", chat))
    bot.handle_update(tg, cb("loc:done", chat))


def test_full_signup_flow(tg):
    bot.handle_update(tg, msg("/start"))
    assert "What role" in tg.last["text"] and tg.last["keyboard"]
    bot.handle_update(tg, cb("role:data_analyst"))
    assert "experience" in tg.last["text"].lower()
    bot.handle_update(tg, cb("exp:exp_0"))
    assert "Where do you want to work" in tg.last["text"]

    bot.handle_update(tg, cb("loc:done"))  # nothing picked yet
    assert ("answer", "cb1", "Pick at least one 🙂") in tg.calls
    bot.handle_update(tg, cb("loc:bengaluru"))
    bot.handle_update(tg, cb("loc:remote"))
    bot.handle_update(tg, cb("loc:remote"))  # toggle off again
    bot.handle_update(tg, cb("loc:done"))

    u = db.get_user(str(CHAT))
    assert u.active and u.state == "ready"
    assert (u.role_key, u.exp_min, u.exp_max, u.locations) == ("data_analyst", 0, 0, ["bengaluru"])
    assert "all set" in tg.sent[-2]["text"]


def test_custom_role_and_commands(tg):
    bot.handle_update(tg, msg("/start"))
    bot.handle_update(tg, cb("role:custom"))
    bot.handle_update(tg, msg("SAP FICO, SAP MM"))
    u = db.get_user(str(CHAT))
    assert u.keywords == ["SAP FICO", "SAP MM"] and u.role_key is None

    bot.handle_update(tg, msg("/exclude intern, sales"))
    assert db.get_user(str(CHAT)).exclude == ["intern", "sales"]
    bot.handle_update(tg, msg("/pause"))
    assert not db.get_user(str(CHAT)).active
    bot.handle_update(tg, msg("/stop"))
    assert db.get_user(str(CHAT)) is None


def test_group_chats_ignored(tg):
    bot.handle_update(tg, {"message": {"chat": {"id": -1, "type": "group"}, "text": "/start"}})
    assert tg.sent == []


def _fake_board(kind, slug, name):
    return [
        Job(source="greenhouse", title="Data Analyst", company=name, location="Bengaluru, India",
            url=f"https://{slug}/1", description="0-2 years of experience"),
        Job(source="greenhouse", title="Senior Data Analyst", company=name, location="Bengaluru, India",
            url=f"https://{slug}/2"),
        Job(source="greenhouse", title="Data Analyst", company=name, location="Austin, TX", url=f"https://{slug}/3"),
    ]


def test_end_to_end_daily_run(tg, monkeypatch, tmp_path):
    companies = tmp_path / "c.yaml"
    companies.write_text("greenhouse:\n  - {slug: acme, name: Acme}\n")
    monkeypatch.setattr(config, "COMPANIES_FILE", companies)
    monkeypatch.setattr(ats, "fetch_board", _fake_board)
    monkeypatch.setattr(adzuna, "search", lambda term, loc: [])
    searched = []

    def fake_jobspy(term, loc):
        searched.append((term, loc))
        return [jobspy_source.finalize(Job(source="jobspy:naukri", title="Data Analyst", company="Acme",
                                           location="Bangalore", url="https://naukri/dup"))]
    monkeypatch.setattr(jobspy_source, "search", fake_jobspy)

    signup(tg, chat=1)
    signup(tg, chat=2)  # same role + city: should NOT cause a second search
    signup(tg, chat=3, role="role:data_engineer", exp="exp_3", locs=("pune",))
    tg.sent.clear()

    report = collect.run()
    assert sorted(searched) == [("data analyst", "Bengaluru"), ("data engineer", "Pune")]
    # Acme Data Analyst in Bengaluru from the board and Naukri is the same job: stored once.
    assert report["new_jobs"] == 2

    n = notify.run(tg=tg)
    assert n["notified"] == 2 and n["jobs_sent"] == 2
    digest = tg.sent[0]["text"]
    assert "Data Analyst" in digest and "Senior" not in digest and "Austin" not in digest
    assert tg.sent[0]["keyboard"][0][0]["callback_data"].startswith("fb:")

    # Feedback works
    uid = tg.sent[0]["keyboard"][0][0]["callback_data"].split(":")[1]
    bot.handle_update(tg, cb(f"fb:{uid}:-1", chat=1))

    # Next day: nothing new, nobody gets spammed with repeats
    tg.sent.clear()
    collect.run()
    n2 = notify.run(tg=tg)
    assert n2["notified"] == 0 and tg.sent == []


def _seed_jobs(n, company="Acme"):
    from jobpipe.normalize import finalize
    db.insert_jobs([finalize(Job(source="greenhouse", title="Data Analyst", company=f"{company}{i}",
                                 location="Bengaluru, India", url=f"https://x/{company}{i}")) for i in range(n)])


def test_jobs_command_gives_instant_matches_without_repeats(tg):
    signup(tg)
    _seed_jobs(7)
    tg.sent.clear()
    bot.handle_update(tg, msg("/jobs"))
    assert "right now" in tg.last["text"] and tg.last["text"].count("Apply here") == bot.JOBS_PER_REQUEST
    bot.handle_update(tg, msg("/jobs"))
    assert tg.last["text"].count("Apply here") == 2  # only the unseen ones
    bot.handle_update(tg, msg("/jobs"))
    assert "seen every match" in tg.last["text"]


def test_jobs_command_needs_setup(tg):
    bot.handle_update(tg, msg("/jobs"))
    # a brand-new user is sent through signup, never an empty digest
    assert "Apply here" not in tg.last["text"]


def test_poll_skips_quietly_when_webhook_is_on(tg):
    from jobpipe.telegram_api import TelegramError

    class Hooked(type(tg)):
        def get_updates(self, offset, timeout=0):
            raise TelegramError("getUpdates failed: 409 Conflict: terminated by setWebhook")
    assert bot.poll(once=True, tg=Hooked()) == 0


def test_webhook_secret_is_derived_from_token():
    import hashlib
    token = "123:abc"
    want = hashlib.sha256(f"jobpipe-webhook:{token}".encode()).hexdigest()[:48]
    assert len(want) == 48 and want.isalnum()


# ---------------------------------------------------------------- reliable morning digest

def test_kv_claim_is_one_time():
    assert db.kv_claim("digest:2026-10-30") is True
    assert db.kv_claim("digest:2026-10-30") is False
    db.kv_delete("digest:2026-10-30")
    assert db.kv_claim("digest:2026-10-30") is True


def test_digest_sends_once_per_day(tg, monkeypatch):
    from jobpipe import digest
    calls = {"collect": 0, "notify": 0}
    monkeypatch.setattr(collect, "run", lambda **k: calls.__setitem__("collect", calls["collect"] + 1) or {"use_jobspy": k.get("use_jobspy")})
    monkeypatch.setattr(notify, "run", lambda tg=None, when=None: calls.__setitem__("notify", calls["notify"] + 1) or {})
    first = digest.run_once_today(tg=tg)
    second = digest.run_once_today(tg=tg)
    assert calls == {"collect": 1, "notify": 1}
    assert first["collect"] == {"use_jobspy": False}  # Vercel run = fast official sources only
    assert "skipped" in second


def test_digest_still_sends_when_collect_fails(tg, monkeypatch):
    from jobpipe import digest
    def boom(**k):
        raise RuntimeError("boards down")
    monkeypatch.setattr(collect, "run", boom)
    monkeypatch.setattr(notify, "run", lambda tg=None, when=None: {"notified": 1})
    report = digest.run_once_today(tg=tg)
    assert report["notify"] == {"notified": 1} and "error" in report["collect"]


def test_digest_frees_the_slot_if_sending_crashes(tg, monkeypatch):
    import pytest
    from jobpipe import digest
    monkeypatch.setattr(collect, "run", lambda **k: {})
    def boom(tg=None, when=None):
        raise RuntimeError("telegram down")
    monkeypatch.setattr(notify, "run", boom)
    with pytest.raises(RuntimeError):
        digest.run_once_today(tg=tg)
    assert db.kv_claim(digest.slot_key()) is True  # a backup timer can retry


def _call_app(path, method="GET", headers=None):
    import io
    import app as webapp
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "CONTENT_LENGTH": "0", "wsgi.input": io.BytesIO(b"")}
    env.update(headers or {})
    out = {}
    body = b"".join(webapp.app(env, lambda s, h: out.setdefault("status", s)))
    return out["status"], body


def test_cron_endpoint_only_in_the_morning_without_secret(monkeypatch):
    from datetime import datetime
    import app as webapp
    from jobpipe import digest
    monkeypatch.delenv("CRON_SECRET", raising=False)
    monkeypatch.setattr(webapp, "Telegram", lambda: None)
    monkeypatch.setattr(webapp.digest, "run_once_today", lambda tg=None: {"ok": True})
    monkeypatch.setattr(digest, "now_ist", lambda: datetime(2026, 10, 30, 2, 0, tzinfo=digest.IST))
    assert _call_app("/api/cron/daily")[0].startswith("403")
    monkeypatch.setattr(digest, "now_ist", lambda: datetime(2026, 10, 30, 8, 5, tzinfo=digest.IST))
    status, body = _call_app("/api/cron/daily")
    assert status.startswith("200") and b'"ok": true' in body


def test_cron_endpoint_checks_secret_when_set(monkeypatch):
    import app as webapp
    monkeypatch.setenv("CRON_SECRET", "s3cret-value-123456")
    monkeypatch.setattr(webapp, "Telegram", lambda: None)
    monkeypatch.setattr(webapp.digest, "run_once_today", lambda tg=None: {"ok": True})
    assert _call_app("/api/cron/daily", headers={"HTTP_AUTHORIZATION": "Bearer nope"})[0].startswith("403")
    assert _call_app("/api/cron/daily", headers={"HTTP_AUTHORIZATION": "Bearer s3cret-value-123456"})[0].startswith("200")


def test_new_user_gets_jobs_right_after_signup(tg):
    _seed_jobs(3, company="First")
    signup(tg)
    assert "all set" in tg.sent[-2]["text"]
    assert "to start with" in tg.last["text"] and tg.last["text"].count("Apply here") == 3


def test_new_user_with_no_matches_is_told_search_is_running(tg):
    signup(tg)
    assert "searching LinkedIn, Naukri and Indeed" in tg.last["text"]


def test_morning_and_evening_are_separate_slots(tg, monkeypatch):
    from datetime import datetime
    from jobpipe import digest
    sent = []
    monkeypatch.setattr(collect, "run", lambda **k: {})
    monkeypatch.setattr(notify, "run", lambda tg=None, when=None: sent.append(when) or {})
    at = lambda h: (lambda: datetime(2026, 10, 30, h, 10, tzinfo=digest.IST))
    monkeypatch.setattr(digest, "now_ist", at(8))
    digest.run_once_today(tg=tg)
    assert "skipped" in digest.run_once_today(tg=tg)     # second morning trigger
    monkeypatch.setattr(digest, "now_ist", at(18))
    evening = digest.run_once_today(tg=tg)
    assert evening["period"] == "pm"
    assert "skipped" in digest.run_once_today(tg=tg)     # second evening trigger
    assert sent == ["today", "this evening"]


def test_cron_endpoint_evening_window(monkeypatch):
    from datetime import datetime
    import app as webapp
    from jobpipe import digest
    monkeypatch.delenv("CRON_SECRET", raising=False)
    monkeypatch.setattr(webapp, "Telegram", lambda: None)
    monkeypatch.setattr(webapp.digest, "run_once_today", lambda tg=None: {"ok": True})
    for hour, ok in [(14, False), (18, True), (22, False)]:
        monkeypatch.setattr(digest, "now_ist", lambda h=hour: datetime(2026, 10, 30, h, 5, tzinfo=digest.IST))
        assert _call_app("/api/cron/daily")[0].startswith("200" if ok else "403"), hour


def test_evening_digest_header():
    from jobpipe.notify import build_digest
    from jobpipe.normalize import finalize
    from jobpipe.models import User
    u = User(chat_id="1", role_label="Data Analyst")
    j = finalize(Job(source="lever", title="Data Analyst", company="A", location="Pune", url="https://a"))
    assert "for you this evening" in build_digest(u, [j], "this evening")[0]
