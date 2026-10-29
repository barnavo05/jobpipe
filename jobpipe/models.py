from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class Job:
    source: str
    title: str
    company: str
    location: str
    url: str
    description: str = ""
    is_remote: bool = False
    posted_at: str | None = None
    exp_min: int | None = None
    exp_max: int | None = None
    uid: str = ""
    fetched_at: str = field(default_factory=utcnow_iso)


@dataclass
class User:
    chat_id: str
    name: str = ""
    role_key: str | None = None
    role_label: str | None = None
    keywords: list[str] = field(default_factory=list)  # for custom roles
    exp_min: int | None = None
    exp_max: int | None = None
    locations: list[str] = field(default_factory=list)  # canonical city keys, "india", "remote"
    exclude: list[str] = field(default_factory=list)
    state: str = "new"  # signup step
    active: bool = False

    @property
    def remote_ok(self) -> bool:
        return "remote" in self.locations
