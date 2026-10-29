"""All settings come from environment variables (or a local .env file)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Tiny .env loader so we don't need python-dotenv."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def _env(name: str, default: str = "") -> str:
    """GitHub passes unset secrets as empty strings, so treat "" as unset."""
    return (os.environ.get(name) or "").strip() or default


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


# Storage: SQLite locally, Supabase Postgres in production.
DATABASE_URL = _env("DATABASE_URL", f"sqlite:///{ROOT / 'jobpipe.db'}")

# Telegram
TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = _env("ADMIN_CHAT_ID")  # optional: gets run reports

# Adzuna (optional, free key from developer.adzuna.com)
ADZUNA_APP_ID = _env("ADZUNA_APP_ID")
ADZUNA_APP_KEY = _env("ADZUNA_APP_KEY")

# JobSpy (Indeed / LinkedIn / Naukri scraping). Keep volume low to avoid blocks.
JOBSPY_ENABLED = _env("JOBSPY_ENABLED", "1") == "1"
JOBSPY_SITES = [s.strip() for s in _env("JOBSPY_SITES", "indeed,linkedin,naukri").split(",") if s.strip()]
JOBSPY_RESULTS = _int("JOBSPY_RESULTS", 30)
HOURS_OLD = _int("HOURS_OLD", 48)

# Limits
MAX_SEARCH_QUERIES = _int("MAX_SEARCH_QUERIES", 25)  # distinct (role, city) searches per run
MAX_JOBS_PER_USER = _int("MAX_JOBS_PER_USER", 10)  # per daily digest
JOB_LOOKBACK_DAYS = _int("JOB_LOOKBACK_DAYS", 3)  # only alert on recently fetched jobs
JOB_RETENTION_DAYS = _int("JOB_RETENTION_DAYS", 30)

COMPANIES_FILE = Path(_env("COMPANIES_FILE", str(ROOT / "config" / "companies.yaml")))

# Supabase "Direct connection" URLs are IPv6 only and fail on GitHub runners.
# Set this to your session pooler host and direct URLs get rewritten automatically.
SUPABASE_POOLER_HOST = _env("SUPABASE_POOLER_HOST")
