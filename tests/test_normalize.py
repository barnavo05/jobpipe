import pytest

from jobpipe.models import Job
from jobpipe.normalize import (clean_text, detect_cities, extract_experience, finalize, is_india,
                               job_uid, looks_remote, remote_open_to_india)


@pytest.mark.parametrize("title,desc,expected", [
    ("Data Analyst", "We need 2-4 years of experience in SQL.", (2, 4)),
    ("Data Analyst", "Experience: 0 to 2 yrs", (0, 2)),
    ("Data Engineer", "3+ years experience with Spark", (3, None)),
    ("ML Engineer", "Minimum 5 years of relevant experience", (5, None)),
    ("Data Analyst (1-3 Yrs)", "", (1, 3)),
    ("Senior Data Scientist", "Great team.", (4, None)),
    ("Data Analyst Intern", "", (0, 1)),
    ("Associate Product Manager", "", (0, 2)),
    ("Staff Engineer", "", (8, None)),
    ("Data Analyst", "Founded 10 years ago, we are a leading company.", (None, None)),
    ("Data Analyst", "", (None, None)),
])
def test_experience(title, desc, expected):
    assert extract_experience(title, desc) == expected


def test_cities_and_india():
    assert detect_cities("Bangalore, Karnataka, India") == {"bengaluru"}
    assert detect_cities("Gurgaon / Noida") == {"delhi_ncr"}
    assert detect_cities("San Francisco, CA") == set()
    assert is_india("Remote, India")
    assert not is_india("London, UK")


def test_remote_rules():
    assert looks_remote("Remote - India")
    assert looks_remote("", "Data Analyst (Work From Home)")
    assert remote_open_to_india("Remote")
    assert remote_open_to_india("Remote - India")
    assert remote_open_to_india("Remote (Worldwide)")
    assert not remote_open_to_india("Remote - US")
    assert not remote_open_to_india("Remote, Germany")


def test_uid_dedupes_across_portals():
    a = job_uid("Razorpay", "Data Analyst", "Bengaluru, Karnataka, India")
    b = job_uid("razorpay", "Data Analyst ", "Bangalore")
    c = job_uid("Razorpay", "Data Analyst", "Pune")
    assert a == b != c


def test_clean_text_handles_double_escaped_html():
    raw = "&lt;p&gt;Hello &amp;amp; welcome&lt;/p&gt;&lt;ul&gt;&lt;li&gt;SQL&lt;/li&gt;&lt;/ul&gt;"
    assert clean_text(raw) == "Hello & welcome\nSQL"


def test_finalize_fills_fields():
    j = finalize(Job(source="x", title="Junior Data Analyst", company="Acme", location="Remote, India", url="u"))
    assert j.is_remote and j.exp_min == 0 and j.uid
