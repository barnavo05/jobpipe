import pandas as pd

from jobpipe.normalize import finalize
from jobpipe.sources import adzuna, ats, jobspy_source

GREENHOUSE = {"jobs": [
    {"id": 1, "title": "Data Analyst", "absolute_url": "https://x/1", "location": {"name": "Bengaluru, India"},
     "updated_at": "2026-10-28T10:00:00-04:00", "content": "&lt;p&gt;2-4 years of experience&lt;/p&gt;"},
    {"id": 2, "title": "Account Executive", "absolute_url": "https://x/2", "location": {"name": "New York"},
     "updated_at": "2026-10-28T10:00:00-04:00", "content": ""},
]}

LEVER = [
    {"id": "a", "text": "Data Engineer", "hostedUrl": "https://lever/a",
     "categories": {"location": "Bangalore", "allLocations": ["Bangalore", "Pune"]},
     "workplaceType": "onsite", "createdAt": 1761700000000, "descriptionPlain": "3+ years experience", "additionalPlain": ""},
    {"id": "b", "text": "ML Engineer", "hostedUrl": "https://lever/b", "categories": {"location": "Remote"},
     "workplaceType": "remote", "createdAt": 1761700000000, "descriptionPlain": ""},
]

ASHBY = {"jobs": [
    {"title": "AI Engineer", "location": "Bengaluru", "secondaryLocations": [{"location": "Remote - India"}],
     "isRemote": False, "jobUrl": "https://ashby/1", "publishedAt": "2026-10-27T00:00:00Z",
     "descriptionPlain": "1-3 yrs exp", "isListed": True},
    {"title": "Hidden", "location": "Bengaluru", "isListed": False, "jobUrl": "https://ashby/2"},
]}

ADZUNA = {"results": [
    {"title": "Data Analyst", "company": {"display_name": "Acme"}, "location": {"display_name": "Bangalore, Karnataka"},
     "redirect_url": "https://adzuna/1", "created": "2026-10-28T00:00:00Z", "description": "Fresher role"},
]}


def test_greenhouse():
    jobs = [finalize(j) for j in ats.parse_greenhouse(GREENHOUSE, "Acme")]
    assert len(jobs) == 2
    assert jobs[0].exp_min == 2 and jobs[0].exp_max == 4
    kept = [j for j in jobs if ats.india_relevant(j)]
    assert [j.title for j in kept] == ["Data Analyst"]


def test_lever():
    jobs = [finalize(j) for j in ats.parse_lever(LEVER, "Acme")]
    assert jobs[0].location == "Bangalore / Pune"
    assert jobs[0].exp_min == 3
    assert jobs[1].is_remote and ats.india_relevant(jobs[1])
    assert jobs[0].posted_at.startswith("2025") or jobs[0].posted_at.startswith("2026")


def test_ashby_skips_unlisted():
    jobs = ats.parse_ashby(ASHBY, "Acme")
    assert len(jobs) == 1 and "Remote - India" in jobs[0].location


def test_adzuna():
    jobs = adzuna.parse(ADZUNA)
    assert jobs[0].company == "Acme" and jobs[0].url == "https://adzuna/1"


def test_jobspy_dataframe():
    df = pd.DataFrame([
        {"site": "naukri", "title": "Data Analyst", "company": "Foo", "location": "Bengaluru",
         "job_url": "https://naukri/1", "job_url_direct": None, "description": "SQL", "is_remote": False,
         "date_posted": "2026-10-28", "experience_range": "0-2 Yrs"},
        {"site": "linkedin", "title": "Data Analyst", "company": "Bar", "location": "Pune, India",
         "job_url": "https://li/1", "job_url_direct": float("nan"), "description": float("nan"),
         "is_remote": float("nan"), "date_posted": float("nan")},
    ])
    jobs = [finalize(j) for j in jobspy_source.parse_dataframe(df)]
    assert jobs[0].source == "jobspy:naukri" and (jobs[0].exp_min, jobs[0].exp_max) == (0, 2)
    assert jobs[1].url == "https://li/1" and jobs[1].posted_at is None


def test_load_companies(tmp_path):
    f = tmp_path / "c.yaml"
    f.write_text("greenhouse:\n  - {slug: foo, name: Foo Inc}\nlever:\n  - bar-baz\n")
    assert ats.load_companies(f) == [("greenhouse", "foo", "Foo Inc"), ("lever", "bar-baz", "Bar Baz")]
