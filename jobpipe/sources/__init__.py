"""Job sources.

Two kinds:
  * board sources (Greenhouse, Lever, Ashby): fetch a company's whole public job board.
    These are official public APIs, free, no key, and allowed.
  * search sources (Adzuna, JobSpy): fetch by search term + city.
"""
from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger("jobpipe.sources")

_session = requests.Session()
_session.headers.update({"User-Agent": "JobPipe/0.1 (+https://github.com/; free job alerts)", "Accept": "application/json"})


class SourceError(Exception):
    pass


def get_json(url: str, params: dict | None = None, retries: int = 2, timeout: int = 25):
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = _session.get(url, params=params, timeout=timeout)
            if resp.status_code == 404:
                raise SourceError(f"404 Not Found: {url}")
            if resp.status_code == 429 or resp.status_code >= 500:
                raise requests.HTTPError(f"HTTP {resp.status_code}")
            resp.raise_for_status()
            return resp.json()
        except SourceError:
            raise
        except Exception as exc:  # network blips, 429s, bad JSON
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise SourceError(f"{url}: {last}")
