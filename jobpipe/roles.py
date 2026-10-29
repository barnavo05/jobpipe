"""Preset roles: what to search for and which job titles count as a match."""
from __future__ import annotations

import re

# key -> (label, search term, title patterns)
ROLES: dict[str, tuple[str, str, list[str]]] = {
    "data_analyst": ("Data Analyst", "data analyst", [
        "data analyst", "business intelligence", "bi analyst", "bi developer", "reporting analyst",
        "insights analyst", "product analyst", "analytics analyst", "mis analyst", "power bi", "tableau",
    ]),
    "data_scientist": ("Data Scientist", "data scientist", [
        "data scientist", "applied scientist", "research scientist", "decision scientist", "machine learning scientist",
    ]),
    "data_engineer": ("Data Engineer", "data engineer", [
        "data engineer", "etl", "big data", "analytics engineer", "data platform", "data pipeline", "spark developer",
    ]),
    "ml_engineer": ("ML / AI Engineer", "machine learning engineer", [
        "machine learning", "ml engineer", "mlops", "ai engineer", "ai/ml", "ai ml", "deep learning",
        "computer vision", "nlp", "llm", "generative ai", "gen ai", "genai",
    ]),
    "software_engineer": ("Software Engineer", "software engineer", [
        "software engineer", "software developer", "sde", "backend", "back end", "full stack", "fullstack",
        "frontend", "front end", "python developer", "java developer", "web developer", "application developer",
    ]),
    "devops": ("DevOps / Cloud", "devops engineer", [
        "devops", "site reliability", "sre", "cloud engineer", "platform engineer", "infrastructure engineer",
    ]),
    "product_manager": ("Product Manager", "product manager", [
        "product manager", "associate product manager", "apm", "product owner",
    ]),
    "business_analyst": ("Business Analyst", "business analyst", [
        "business analyst", "business analytics", "strategy analyst", "operations analyst",
    ]),
}


def _pattern(term: str) -> re.Pattern:
    return re.compile(r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])")


_COMPILED = {k: [_pattern(t) for t in v[2]] for k, v in ROLES.items()}


def title_matches(title: str, role_key: str | None, keywords: list[str] | None = None) -> bool:
    """Preset role: any pattern hits. Custom role: every word of any keyword phrase appears."""
    t = (title or "").lower()
    if role_key and role_key in _COMPILED:
        return any(p.search(t) for p in _COMPILED[role_key])
    for phrase in keywords or []:
        words = [w for w in re.split(r"\W+", phrase.lower()) if w]
        if words and all(_pattern(w).search(t) for w in words):
            return True
    return False


def search_term_for(role_key: str | None, keywords: list[str] | None) -> str | None:
    if role_key and role_key in ROLES:
        return ROLES[role_key][1]
    return keywords[0] if keywords else None


EXPERIENCE_BUCKETS: dict[str, tuple[str, int, int]] = {
    "exp_0": ("Fresher (0 yrs)", 0, 0),
    "exp_1": ("1 to 2 yrs", 1, 2),
    "exp_3": ("3 to 5 yrs", 3, 5),
    "exp_6": ("6 to 9 yrs", 6, 9),
    "exp_10": ("10+ yrs", 10, 40),
}
