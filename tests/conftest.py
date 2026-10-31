import pytest

from jobpipe import config, db


class FakeTelegram:
    """Records everything the bot would send."""

    def __init__(self):
        self.sent: list[dict] = []
        self.calls: list[tuple] = []
        self._mid = 100

    def send(self, chat_id, text, keyboard=None):
        self._mid += 1
        self.sent.append({"chat_id": str(chat_id), "text": text, "keyboard": keyboard, "message_id": self._mid})
        return {"message_id": self._mid}

    def edit_keyboard(self, chat_id, message_id, keyboard):
        self.calls.append(("edit_keyboard", str(chat_id), message_id, keyboard))

    def edit(self, *a, **k):
        self.calls.append(("edit", a, k))

    def answer_callback(self, cid, text="", alert=False):
        self.calls.append(("answer", cid, text, alert))

    def call(self, method, **params):
        self.calls.append((method, params))

    @property
    def last(self):
        return self.sent[-1]


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setattr(config, "DATABASE_URL", url)
    db.engine.cache_clear()
    db.init_db()
    yield
    db.engine.cache_clear()


@pytest.fixture
def tg():
    return FakeTelegram()
