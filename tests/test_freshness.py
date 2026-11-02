"""Fresh vs reposted vs stale jobs, and the tags users see."""
from datetime import datetime, timedelta, timezone

from jobpipe import db, freshness, notify
from jobpipe.match import score
from jobpipe.models import Job, User
from jobpipe.normalize import finalize

NOW = datetime(2026, 11, 2, 6, 0, tzinfo=timezone.utc)  # 11:30 AM IST


def iso(dt):
    return dt.replace(microsecond=0).isoformat()


def job(company="Acme", source="greenhouse", posted=None, **kw):
    return finalize(Job(source=source, title="Data Analyst", company=company, location="Bengaluru, India",
                        url=f"https://x/{company}", posted_at=posted, **kw))


# ---------------------------------------------------------------- pure rules

def test_fresh_company_job_is_early():
    j = job(posted=iso(NOW - timedelta(hours=3)), first_seen=iso(NOW - timedelta(hours=1)))
    assert freshness.is_fresh(j, NOW)
    assert freshness.tag(j, NOW) == "🆕 Posted 3 hrs ago on the company site. You're early"


def test_portal_job_with_date_only_says_today_or_yesterday():
    j = job(source="jobspy:naukri", posted="2026-11-01", first_seen=iso(NOW - timedelta(hours=5)))
    assert freshness.tag(j, NOW) == "🆕 Posted yesterday"
    j = job(source="jobspy:linkedin", posted="2026-11-02", first_seen=iso(NOW))
    assert freshness.tag(j, NOW) == "🆕 Posted today"


def test_old_job_that_was_just_edited_is_not_fresh():
    # Greenhouse falls back to updated_at, so an edit gives an old job a new date.
    # We've known it for two weeks, so it's not new.
    j = job(posted=iso(NOW - timedelta(hours=2)), first_seen=iso(NOW - timedelta(days=14)))
    assert not freshness.is_fresh(j, NOW)
    assert freshness.tag(j, NOW) == ""


def test_back_after_a_gap_counts_as_repost():
    j = job()
    row = freshness.next_history(None, j, NOW - timedelta(days=40))
    row = freshness.next_history(row, j, NOW - timedelta(days=39))      # seen again next day: same listing
    assert row["reposts"] == 0
    row = freshness.next_history(row, j, NOW)                            # gone 39 days, back again
    assert row["reposts"] == 1 and row["first_seen"] == iso(NOW - timedelta(days=40))


def test_posted_date_jumping_forward_counts_as_repost():
    first = job(source="jobspy:linkedin", posted="2026-10-10")
    row = freshness.next_history(None, first, NOW - timedelta(days=20))
    bumped = job(source="jobspy:linkedin", posted="2026-11-01")
    row = freshness.next_history(row, bumped, NOW)
    assert row["reposts"] == 1
    assert row["first_posted"].startswith("2026-10-09")  # Oct 10 IST, kept as the original date


def test_daily_sightings_are_not_reposts():
    j = job(posted=iso(NOW - timedelta(days=5)))
    row = None
    for d in range(5, -1, -1):
        row = freshness.next_history(row, j, NOW - timedelta(days=d))
    assert row["reposts"] == 0


def test_repost_tag_names_the_original_month():
    j = job(source="jobspy:linkedin", posted="2026-11-01", first_posted="2026-08-14", reposts=3,
            first_seen=iso(NOW - timedelta(days=60)))
    assert freshness.tag(j, NOW) == "♻️ Reposted 3x since Aug 14, may never close"
    assert not freshness.is_fresh(j, NOW)  # a fresh date on a reposted job doesn't make it new


def test_stale_job():
    j = job(posted=iso(NOW - timedelta(days=45)), first_seen=iso(NOW - timedelta(days=2)))
    assert freshness.tag(j, NOW).startswith("⏳ Open since Sep 18")


def test_ranking_prefers_fresh_over_ghost():
    user = User(chat_id="1", role_key="data_analyst", exp_min=0, exp_max=1, locations=["bengaluru"])
    now = datetime.now(timezone.utc)
    fresh = job("A", posted=iso(now - timedelta(hours=2)), first_seen=iso(now))
    ghost = job("B", posted=iso(now - timedelta(hours=2)), first_seen=iso(now - timedelta(days=50)), reposts=2)
    assert score(fresh, user) > score(ghost, user)


def test_garbage_dates_never_crash():
    j = job(posted="last week", first_seen=None)
    assert freshness.tag(j, NOW) == "" and not freshness.is_ghosty(j, NOW)


# ---------------------------------------------------------------- database

def test_history_recorded_and_attached_to_jobs():
    j = job(posted=iso(datetime.now(timezone.utc) - timedelta(hours=3)))
    db.insert_jobs([j])
    assert db.record_seen([j]) == 0
    loaded = db.recent_jobs()[0]
    assert loaded.first_seen and loaded.reposts == 0
    assert "🆕 Posted 3 hrs ago" in notify.format_job(1, loaded)


def test_history_outlives_the_jobs_table_so_reposts_are_caught():
    old = datetime.now(timezone.utc) - timedelta(days=45)
    j = job(fetched_at=iso(old))
    db.insert_jobs([j])
    db.record_seen([j], now=old)
    db.prune_jobs()                      # the 30 day cleanup removes the job...
    assert db.get_job(j.uid) is None
    again = job()                        # ...it shows up again today
    db.insert_jobs([again])
    assert db.record_seen([again]) == 1
    loaded = db.get_job(again.uid)
    assert loaded.reposts == 1
    assert "♻️ Reposted once" in notify.format_job(1, loaded)


def test_backfill_starts_history_from_existing_jobs(tmp_path):
    url = f"sqlite:///{tmp_path}/old.db"
    from sqlalchemy import create_engine, text
    eng = create_engine(url)
    with eng.begin() as c:  # a database from before this feature: jobs, no history
        c.execute(text("CREATE TABLE jobs (uid TEXT PRIMARY KEY, source TEXT, title TEXT, company TEXT, "
                       "location TEXT, url TEXT, description TEXT, is_remote INTEGER DEFAULT 0, "
                       "exp_min INTEGER, exp_max INTEGER, posted_at TEXT, fetched_at TEXT)"))
        c.execute(text("INSERT INTO jobs (uid, title, company, fetched_at) VALUES ('u1', 't', 'c', '2026-10-05T00:00:00+00:00')"))
    db.init_db(url)
    db.init_db(url)  # second run is a no-op
    with eng.connect() as c:
        rows = c.execute(text("SELECT uid, first_seen FROM job_history")).all()
    assert rows == [("u1", "2026-10-05T00:00:00+00:00")]


def test_backfilled_job_still_open_is_not_a_repost(tmp_path):
    """Old rows only know when a job was first inserted, not when it was last seen,
    so a job that's simply still open must not look like it vanished and came back."""
    test_backfill_starts_history_from_existing_jobs(tmp_path)
    from jobpipe import config
    config.DATABASE_URL = f"sqlite:///{tmp_path}/old.db"
    db.engine.cache_clear()
    still_open = Job(source="lever", title="t", company="c", location="", url="u", uid="u1")
    assert db.record_seen([still_open]) == 0
    with db.engine().connect() as c:
        from sqlalchemy import text
        assert c.execute(text("SELECT reposts, last_seen IS NOT NULL FROM job_history")).one() == (0, True)
