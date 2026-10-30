from jobpipe import config, db
from jobpipe.telegram_api import TelegramError, redact

FAKE = "1234567890:AAHk3abcdefghijklmnopqrstuvwxyz0123"


def test_token_never_in_error_text(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", FAKE)
    msg = f"Max retries exceeded with url: /bot{FAKE}/sendMessage"
    assert FAKE not in redact(msg)
    assert FAKE not in str(TelegramError(msg))


def test_token_shaped_strings_redacted_without_config(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    assert "AAHk3" not in redact(f"url /bot{FAKE}/getUpdates")


def test_postgres_tables_get_locked_down():
    stmts = " ".join(db._lockdown_statements())
    for t in db.TABLES:
        assert f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY" in stmts
