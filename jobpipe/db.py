"""Storage layer. Same SQL runs on SQLite (local dev) and Postgres (Supabase free tier)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from . import config
from .models import Job, User, utcnow_iso

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        chat_id TEXT PRIMARY KEY,
        name TEXT,
        role_key TEXT,
        role_label TEXT,
        keywords TEXT DEFAULT '[]',
        exp_min INTEGER,
        exp_max INTEGER,
        locations TEXT DEFAULT '[]',
        exclude TEXT DEFAULT '[]',
        state TEXT DEFAULT 'new',
        active INTEGER DEFAULT 0,
        created_at TEXT,
        updated_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS jobs (
        uid TEXT PRIMARY KEY,
        source TEXT,
        title TEXT,
        company TEXT,
        location TEXT,
        url TEXT,
        description TEXT,
        is_remote INTEGER DEFAULT 0,
        exp_min INTEGER,
        exp_max INTEGER,
        posted_at TEXT,
        fetched_at TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_jobs_fetched ON jobs (fetched_at)",
    """CREATE TABLE IF NOT EXISTS sent (
        chat_id TEXT,
        uid TEXT,
        sent_at TEXT,
        feedback INTEGER,
        PRIMARY KEY (chat_id, uid)
    )""",
    "CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)",
]


_SUPABASE_DIRECT = re.compile(
    r"^(?P<scheme>[a-z+]+://)(?P<user>postgres(?:\.[a-z0-9]+)?):(?P<pw>[^@]*)@db\.(?P<ref>[a-z0-9]+)\.supabase\.co"
    r"(?::\d+)?(?:/.*)?$")


def _supabase_direct_to_pooler(url: str) -> str:
    """Supabase's "Direct connection" URL is IPv6 only, and GitHub runners are IPv4 only.
    If SUPABASE_POOLER_HOST is set, quietly rewrite a direct URL to the session pooler."""
    pooler = config.SUPABASE_POOLER_HOST
    m = _SUPABASE_DIRECT.match(url)
    if not (pooler and m):
        return url
    # Anything after the host (even a second pasted address) is dropped; Supabase's db is always "postgres".
    return f"{m['scheme']}postgres.{m['ref']}:{m['pw']}@{pooler}:5432/postgres"


def _normalize_url(url: str) -> str:
    url = _supabase_direct_to_pooler(url)
    # Supabase hands out postgres:// or postgresql:// URLs; use the psycopg v3 driver.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


@lru_cache(maxsize=4)
def engine(url: str | None = None) -> Engine:
    return create_engine(_normalize_url(url or config.DATABASE_URL), pool_pre_ping=True, future=True)


def init_db(url: str | None = None) -> None:
    with engine(url).begin() as conn:
        for stmt in SCHEMA:
            conn.execute(text(stmt))


# ---------------------------------------------------------------- users

USER_FIELDS = ["name", "role_key", "role_label", "keywords", "exp_min", "exp_max",
               "locations", "exclude", "state", "active"]
_JSON_FIELDS = {"keywords", "locations", "exclude"}


def _row_to_user(row) -> User:
    m = row._mapping
    return User(
        chat_id=m["chat_id"], name=m["name"] or "",
        role_key=m["role_key"], role_label=m["role_label"],
        keywords=json.loads(m["keywords"] or "[]"),
        exp_min=m["exp_min"], exp_max=m["exp_max"],
        locations=json.loads(m["locations"] or "[]"),
        exclude=json.loads(m["exclude"] or "[]"),
        state=m["state"] or "new", active=bool(m["active"]),
    )


def get_user(chat_id: str) -> User | None:
    with engine().connect() as conn:
        row = conn.execute(text("SELECT * FROM users WHERE chat_id = :c"), {"c": str(chat_id)}).first()
    return _row_to_user(row) if row else None


def ensure_user(chat_id: str, name: str = "") -> User:
    now = utcnow_iso()
    with engine().begin() as conn:
        conn.execute(text(
            "INSERT INTO users (chat_id, name, created_at, updated_at) VALUES (:c, :n, :t, :t) "
            "ON CONFLICT (chat_id) DO NOTHING"), {"c": str(chat_id), "n": name, "t": now})
    return get_user(chat_id)  # type: ignore[return-value]


def update_user(chat_id: str, **fields) -> User:
    bad = set(fields) - set(USER_FIELDS)
    if bad:
        raise ValueError(f"unknown user fields: {bad}")
    params = {"c": str(chat_id), "t": utcnow_iso()}
    sets = []
    for key, value in fields.items():
        if key in _JSON_FIELDS:
            value = json.dumps(value)
        elif key == "active":
            value = int(bool(value))
        params[key] = value
        sets.append(f"{key} = :{key}")
    sets.append("updated_at = :t")
    with engine().begin() as conn:
        conn.execute(text(f"UPDATE users SET {', '.join(sets)} WHERE chat_id = :c"), params)
    return get_user(chat_id)  # type: ignore[return-value]


def delete_user(chat_id: str) -> None:
    with engine().begin() as conn:
        conn.execute(text("DELETE FROM sent WHERE chat_id = :c"), {"c": str(chat_id)})
        conn.execute(text("DELETE FROM users WHERE chat_id = :c"), {"c": str(chat_id)})


def active_users() -> list[User]:
    with engine().connect() as conn:
        rows = conn.execute(text("SELECT * FROM users WHERE active = 1")).all()
    return [_row_to_user(r) for r in rows]


def count_users() -> tuple[int, int]:
    with engine().connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM users")).scalar_one()
        active = conn.execute(text("SELECT COUNT(*) FROM users WHERE active = 1")).scalar_one()
    return total, active


# ---------------------------------------------------------------- jobs

def insert_jobs(jobs: list[Job]) -> int:
    """Insert new jobs, skip ones we already have. Returns number of new rows."""
    unique: dict[str, Job] = {}
    for j in jobs:
        unique.setdefault(j.uid, j)
    if not unique:
        return 0
    existing: set[str] = set()
    uids = list(unique)
    with engine().connect() as conn:
        for i in range(0, len(uids), 500):
            chunk = uids[i:i + 500]
            params = {f"u{n}": u for n, u in enumerate(chunk)}
            placeholders = ", ".join(f":u{n}" for n in range(len(chunk)))
            rows = conn.execute(text(f"SELECT uid FROM jobs WHERE uid IN ({placeholders})"), params).all()
            existing.update(r[0] for r in rows)
    fresh = [j for u, j in unique.items() if u not in existing]
    if not fresh:
        return 0
    sql = text(
        "INSERT INTO jobs (uid, source, title, company, location, url, description, is_remote, "
        "exp_min, exp_max, posted_at, fetched_at) VALUES (:uid, :source, :title, :company, :location, "
        ":url, :description, :is_remote, :exp_min, :exp_max, :posted_at, :fetched_at) "
        "ON CONFLICT (uid) DO NOTHING")
    with engine().begin() as conn:
        conn.execute(sql, [{
            "uid": j.uid, "source": j.source, "title": j.title, "company": j.company,
            "location": j.location, "url": j.url, "description": j.description,
            "is_remote": int(j.is_remote), "exp_min": j.exp_min, "exp_max": j.exp_max,
            "posted_at": j.posted_at, "fetched_at": j.fetched_at,
        } for j in fresh])
    return len(fresh)


def _row_to_job(row) -> Job:
    m = row._mapping
    return Job(source=m["source"], title=m["title"], company=m["company"], location=m["location"],
               url=m["url"], description=m["description"] or "", is_remote=bool(m["is_remote"]),
               posted_at=m["posted_at"], exp_min=m["exp_min"], exp_max=m["exp_max"],
               uid=m["uid"], fetched_at=m["fetched_at"])


def recent_jobs(days: int | None = None) -> list[Job]:
    since = (datetime.now(timezone.utc) - timedelta(days=days or config.JOB_LOOKBACK_DAYS)).replace(microsecond=0).isoformat()
    with engine().connect() as conn:
        rows = conn.execute(text("SELECT * FROM jobs WHERE fetched_at >= :s ORDER BY fetched_at DESC"), {"s": since}).all()
    return [_row_to_job(r) for r in rows]


def get_job(uid: str) -> Job | None:
    with engine().connect() as conn:
        row = conn.execute(text("SELECT * FROM jobs WHERE uid = :u"), {"u": uid}).first()
    return _row_to_job(row) if row else None


def prune_jobs(days: int | None = None) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days or config.JOB_RETENTION_DAYS)).isoformat()
    with engine().begin() as conn:
        res = conn.execute(text("DELETE FROM jobs WHERE fetched_at < :c"), {"c": cutoff})
    return res.rowcount or 0


# ---------------------------------------------------------------- sent / feedback

def sent_uids(chat_id: str) -> set[str]:
    with engine().connect() as conn:
        rows = conn.execute(text("SELECT uid FROM sent WHERE chat_id = :c"), {"c": str(chat_id)}).all()
    return {r[0] for r in rows}


def mark_sent(chat_id: str, uids: list[str]) -> None:
    if not uids:
        return
    now = utcnow_iso()
    with engine().begin() as conn:
        conn.execute(text("INSERT INTO sent (chat_id, uid, sent_at) VALUES (:c, :u, :t) "
                          "ON CONFLICT (chat_id, uid) DO NOTHING"),
                     [{"c": str(chat_id), "u": uid, "t": now} for uid in uids])


def set_feedback(chat_id: str, uid: str, value: int) -> None:
    with engine().begin() as conn:
        conn.execute(text("UPDATE sent SET feedback = :v WHERE chat_id = :c AND uid = :u"),
                     {"v": value, "c": str(chat_id), "u": uid})


def disliked_companies(chat_id: str, threshold: int = 2) -> set[str]:
    """Companies a user thumbed down at least `threshold` times get muted for them."""
    with engine().connect() as conn:
        rows = conn.execute(text(
            "SELECT j.company, COUNT(*) FROM sent s JOIN jobs j ON j.uid = s.uid "
            "WHERE s.chat_id = :c AND s.feedback = -1 GROUP BY j.company"), {"c": str(chat_id)}).all()
    return {r[0].lower() for r in rows if r[1] >= threshold}


# ---------------------------------------------------------------- kv

def kv_get(key: str, default: str | None = None) -> str | None:
    with engine().connect() as conn:
        row = conn.execute(text("SELECT value FROM kv WHERE key = :k"), {"k": key}).first()
    return row[0] if row else default


def kv_set(key: str, value: str) -> None:
    with engine().begin() as conn:
        conn.execute(text("INSERT INTO kv (key, value) VALUES (:k, :v) "
                          "ON CONFLICT (key) DO UPDATE SET value = excluded.value"), {"k": key, "v": value})
