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
    assert "all set" in tg.last["text"]


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
