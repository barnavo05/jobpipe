from jobpipe.match import is_match, matches_for
from jobpipe.models import Job, User
from jobpipe.normalize import finalize
from jobpipe.roles import title_matches


def job(title, location="Bengaluru, India", desc="", company="Acme", source="greenhouse", remote=False):
    return finalize(Job(source=source, title=title, company=company, location=location,
                        url=f"https://x/{title}", description=desc, is_remote=remote))


fresher_da = User(chat_id="1", role_key="data_analyst", role_label="Data Analyst",
                  exp_min=0, exp_max=0, locations=["bengaluru"], active=True)


def test_titles():
    assert title_matches("Business Intelligence Analyst", "data_analyst")
    assert title_matches("Senior MLOps Engineer", "ml_engineer")
    assert title_matches("SDE-1 Backend", "software_engineer")
    assert not title_matches("Data Entry Operator", "data_analyst")
    assert not title_matches("Sales Executive", "data_analyst")
    assert title_matches("SAP FICO Consultant", None, ["sap fico"])
    assert not title_matches("SAP Basis Admin", None, ["sap fico"])


def test_experience_filter():
    assert is_match(job("Data Analyst", desc="0-2 years experience"), fresher_da)
    assert is_match(job("Data Analyst", desc="1-3 years experience"), fresher_da)  # tolerance
    assert not is_match(job("Data Analyst", desc="4+ years of experience"), fresher_da)
    assert not is_match(job("Senior Data Analyst"), fresher_da)
    assert is_match(job("Data Analyst"), fresher_da)  # unknown exp passes


def test_location_filter():
    assert not is_match(job("Data Analyst", location="Pune"), fresher_da)
    remote_user = User(**{**fresher_da.__dict__, "locations": ["remote"]})
    assert is_match(job("Data Analyst", location="Remote - India", remote=True), remote_user)
    assert not is_match(job("Data Analyst", location="Remote - US", remote=True), remote_user)
    india_user = User(**{**fresher_da.__dict__, "locations": ["india"]})
    assert is_match(job("Data Analyst", location="Hyderabad, Telangana"), india_user)


def test_excludes_and_muted():
    u = User(**{**fresher_da.__dict__, "exclude": ["intern"]})
    assert not is_match(job("Data Analyst Intern"), u)
    assert not is_match(job("Data Analyst", company="SpamCo"), fresher_da, {"spamco"})


def test_ranking_and_dedupe():
    jobs = [job("Data Analyst", company="A", source="jobspy:indeed"),
            job("Data Analyst", company="B", desc="0-1 years experience"),
            job("Product Analyst", company="C")]
    picked = matches_for(fresher_da, jobs, already_sent={jobs[2].uid}, limit=5)
    assert [j.company for j in picked] == ["B", "A"]
