from datetime import datetime, timezone

from jobscan import jobboards, notify


def _c(cid, text, when="2026-11-02T16:00:00Z"):
    return {"id": cid, "text": text, "created_at": when}


def test_hn_ml_role_us_remote_with_visa():
    p = jobboards.parse_hn_comment(_c(1, "Acme AI | Senior ML Engineer | San Francisco, CA or Remote (US) | Full-time | VISA"
                                         "<p>We build LLM agents for insurance. Python, PyTorch, RAG.</p>"))
    assert p.company == "Acme AI"
    assert p.title == "Senior ML Engineer"
    assert "San Francisco, CA" in p.location
    assert p.extra["h1b"] == "visa sponsorship mentioned"
    assert p.url == "https://news.ycombinator.com/item?id=1"
    assert p.posted_at == datetime(2026, 11, 2, 16, tzinfo=timezone.utc)
    assert "LLM agents" in p.description


def test_hn_no_visa_and_non_ml():
    p = jobboards.parse_hn_comment(_c(2, "Beta | AI Engineer | NYC | ONSITE | No visa sponsorship"))
    assert p and p.extra["h1b"] == ""
    assert jobboards.parse_hn_comment(_c(3, "Gamma | Frontend Engineer (React) | Remote | Full-time")) is None
    assert jobboards.parse_hn_comment(_c(4, "just a reply without pipes")) is None


def test_getro_mapping():
    jobs = [{"id": 99, "title": "Machine Learning Engineer", "url": "https://jobs.lever.co/x/99",
             "organization": {"name": "Xco"}, "locations": ["New York, NY, USA"], "created_at": 1793635200},
            {"title": "no url"}]
    out = jobboards.map_getro("general_catalyst", jobs)
    assert len(out) == 1
    p = out[0]
    assert (p.company, p.title, p.location, p.source) == ("Xco", "Machine Learning Engineer", "New York, NY, USA", "vcboards")
    assert p.posted_at.year == 2026


def test_board_names():
    assert notify.BOARD_NAMES["hackernews"].startswith("Hacker News")
    assert notify.BOARD_NAMES["vcboards"] == "VC job boards"
