"""Cleaning helpers: HTML stripping, city detection, experience extraction, dedupe ids."""
from __future__ import annotations

import hashlib
import html
import re

from .models import Job

# canonical key -> (display name, aliases, search location string)
CITIES: dict[str, tuple[str, list[str], str]] = {
    "bengaluru": ("Bengaluru", ["bengaluru", "bangalore", "blr"], "Bengaluru"),
    "hyderabad": ("Hyderabad", ["hyderabad", "secunderabad"], "Hyderabad"),
    "pune": ("Pune", ["pune"], "Pune"),
    "mumbai": ("Mumbai", ["mumbai", "bombay", "navi mumbai", "thane"], "Mumbai"),
    "delhi_ncr": ("Delhi NCR", ["delhi", "new delhi", "ncr", "gurugram", "gurgaon", "noida", "greater noida", "ghaziabad", "faridabad"], "Delhi"),
    "chennai": ("Chennai", ["chennai", "madras"], "Chennai"),
    "kolkata": ("Kolkata", ["kolkata", "calcutta"], "Kolkata"),
    "ahmedabad": ("Ahmedabad", ["ahmedabad", "gandhinagar"], "Ahmedabad"),
    "jaipur": ("Jaipur", ["jaipur"], "Jaipur"),
    "kochi": ("Kochi", ["kochi", "cochin", "trivandrum", "thiruvananthapuram"], "Kochi"),
    "indore": ("Indore", ["indore"], "Indore"),
    "chandigarh": ("Chandigarh", ["chandigarh", "mohali", "panchkula"], "Chandigarh"),
    "coimbatore": ("Coimbatore", ["coimbatore"], "Coimbatore"),
    "bhopal": ("Bhopal", ["bhopal"], "Bhopal"),
}

_INDIA_HINTS = ["india", " in,", ", in", "karnataka", "maharashtra", "telangana", "tamil nadu", "haryana",
                "uttar pradesh", "west bengal", "gujarat", "kerala", "rajasthan", "madhya pradesh"]
_GLOBAL_REMOTE_HINTS = ["anywhere", "worldwide", "global", "apac", "asia"]

_ALIAS_PATTERNS = [
    (key, re.compile(r"\b(" + "|".join(re.escape(a) for a in aliases) + r")\b"))
    for key, (_, aliases, _) in CITIES.items()
]


def clean_text(text: str | None, limit: int = 4000) -> str:
    if not text:
        return ""
    text = html.unescape(html.unescape(str(text)))  # Greenhouse double-escapes
    text = re.sub(r"<(br|/p|/li|/div|/h\d)[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()[:limit]


def detect_cities(location: str | None) -> set[str]:
    loc = (location or "").lower()
    return {key for key, pat in _ALIAS_PATTERNS if pat.search(loc)}


def looks_remote(location: str | None, title: str | None = "") -> bool:
    text = f"{location or ''} {title or ''}".lower()
    return bool(re.search(r"\b(remote|work from home|wfh)\b", text))


def is_india(location: str | None) -> bool:
    loc = f" {(location or '').lower()} "
    return bool(detect_cities(loc)) or any(h in loc for h in _INDIA_HINTS)


def remote_open_to_india(location: str | None) -> bool:
    """A remote job India-based folks can likely take."""
    loc = (location or "").lower().strip()
    if is_india(loc):
        return True
    stripped = re.sub(r"[^a-z ]", " ", loc)
    stripped = re.sub(r"\b(remote|fully|work from home|wfh|hybrid)\b", " ", stripped).strip()
    if not stripped:
        return True  # just "Remote"
    return any(h in loc for h in _GLOBAL_REMOTE_HINTS)


# ---------------------------------------------------------------- experience

_NUM = r"(\d{1,2}(?:\.\d)?)"
_RANGE = re.compile(_NUM + r"\s*(?:-|to|–|—)\s*" + _NUM + r"\s*\+?\s*(?:years?|yrs?)\b", re.I)
_PLUS = re.compile(_NUM + r"\s*\+\s*(?:years?|yrs?)\b", re.I)
_MIN_WORDS = re.compile(r"(?:minimum(?: of)?|at least|min\.?)\s*" + _NUM + r"\s*\+?\s*(?:years?|yrs?)\b", re.I)
_SINGLE = re.compile(_NUM + r"\s*(?:years?|yrs?)\b", re.I)
_EXP_CONTEXT = re.compile(r"experience|exp\b|expertise|work(?:ing)? in|background", re.I)

_TITLE_RULES: list[tuple[re.Pattern, tuple[int, int | None]]] = [
    (re.compile(r"\b(intern|internship|trainee|apprentice|fresher|graduate|new grad|entry[- ]level|campus)\b", re.I), (0, 1)),
    (re.compile(r"\b(junior|jr\.?|associate)\b", re.I), (0, 2)),
    (re.compile(r"\b(principal|staff|architect|director|head of|vp|vice president|distinguished)\b", re.I), (8, None)),
    (re.compile(r"\b(lead|manager|mgr)\b", re.I), (5, None)),
    (re.compile(r"\b(senior|sr\.?)\b", re.I), (4, None)),
    (re.compile(r"\b(ii)\b", re.I), (2, 5)),
    (re.compile(r"\b(iii)\b", re.I), (4, 8)),
]


def _near_experience(text: str, start: int, end: int, window: int = 60) -> bool:
    return bool(_EXP_CONTEXT.search(text[max(0, start - window): end + window]))


def experience_from_text(text: str, need_context: bool = True) -> tuple[int | None, int | None]:
    """need_context=False for titles, where "(1-3 Yrs)" alone clearly means experience."""
    if not text:
        return None, None

    def ok(m) -> bool:
        return not need_context or _near_experience(text, m.start(), m.end())

    for m in _RANGE.finditer(text):
        lo, hi = float(m.group(1)), float(m.group(2))
        if lo <= hi <= 30 and ok(m):
            return int(lo), int(round(hi))
    for pat in (_MIN_WORDS, _PLUS, _SINGLE):
        for m in pat.finditer(text):
            n = float(m.group(1))
            if n <= 25 and ok(m):
                return int(n), None
    return None, None


def experience_from_title(title: str) -> tuple[int | None, int | None]:
    for pat, rng in _TITLE_RULES:
        if pat.search(title or ""):
            return rng
    return None, None


def extract_experience(title: str, description: str) -> tuple[int | None, int | None]:
    """Explicit numbers in the title win, then the description, then seniority words."""
    lo, hi = experience_from_text(title, need_context=False)
    if lo is None:
        lo, hi = experience_from_text(description)
    if lo is None:
        lo, hi = experience_from_title(title)
    return lo, hi


# ---------------------------------------------------------------- ids

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def job_uid(company: str, title: str, location: str) -> str:
    """Same job on 4 portals -> one uid. Location is reduced to its city set."""
    cities = ",".join(sorted(detect_cities(location))) or _norm(location)[:30]
    key = f"{_norm(company)}|{_norm(title)}|{cities}"
    return hashlib.sha1(key.encode()).hexdigest()[:20]


def finalize(job: Job) -> Job:
    """Fill derived fields on a freshly fetched job."""
    job.title = clean_text(job.title, 200)
    job.company = clean_text(job.company, 120) or "Unknown"
    job.location = clean_text(job.location, 200)
    job.description = clean_text(job.description)
    job.is_remote = bool(job.is_remote) or looks_remote(job.location, job.title)
    if job.exp_min is None and job.exp_max is None:
        job.exp_min, job.exp_max = extract_experience(job.title, job.description)
    job.uid = job.uid or job_uid(job.company, job.title, job.location)
    return job
