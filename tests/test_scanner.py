import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from jobscan import fetchers, matching

RESUME = open("resume.txt").read()


# ----------------------------- matching -----------------------------------
@pytest.mark.parametrize("title,ok", [
    ("AI Engineer", True),
    ("Machine Learning Engineer, Ads", True),
    ("Applied AI Engineer", True),
    ("GenAI Engineer", True),
    ("AI/ML Engineer II", True),
    ("Forward Deployed Engineer, AI", True),
    ("Senior Machine Learning Engineer", False),
    ("Staff AI Engineer", False),
    ("Lead ML Engineer", False),
    ("Machine Learning Engineer Intern", False),
    ("Research Scientist, LLM", False),
    ("Software Engineer, Payments", False),
    ("AI Sales Specialist", False),
    ("Computer Vision Engineer", False),
])
def test_titles(title, ok):
    import yaml
    cfg = yaml.safe_load(open("config.yaml"))
    inc = matching.compile_patterns(cfg["title_include"])
    exc = matching.compile_patterns(cfg["title_exclude"])
    assert matching.title_ok(title, inc, exc) is ok


@pytest.mark.parametrize("loc,country,ok", [
    ("San Francisco, CA", None, True),
    ("Remote - US", None, True),
    ("New York, NY / Remote", None, True),
    ("Dallas, Texas", None, True),
    ("Remote", None, True),
    ("Bengaluru, India", None, False),
    ("London, UK", None, False),
    ("Berlin, DE", None, False),
    ("Toronto, ON", None, False),
    ("Anywhere", "IN", False),
    ("Hybrid", "United States", True),
    ("Washington, DC", None, True),
])
def test_locations(loc, country, ok):
    assert matching.is_us_location(loc, country) is ok


def test_disqualifiers():
    assert "No sponsorship" in matching.disqualifiers("We are unable to sponsor visas for this role.")
    assert "No sponsorship" in matching.disqualifiers(
        "Candidates must be authorized to work in the US without the need for current or future sponsorship.")
    assert "US citizens only" in matching.disqualifiers("Must be a U.S. citizen.")
    assert "Security clearance" in matching.disqualifiers("Active TS/SCI clearance required.")
    assert "Green card / citizens only" in matching.disqualifiers("Open to US citizens or green card holders only.")
    # EEO boilerplate must NOT trigger
    assert matching.disqualifiers(
        "All applicants receive consideration without regard to race, religion, national origin, citizenship status.") == []
    assert matching.disqualifiers("We do sponsor visas for this role!") == []


def test_years():
    assert matching.years_required("5+ years of software engineering experience, 2+ years with LLMs") == 5
    assert matching.years_required("3-5 years of professional experience") == 3
    assert matching.years_required("We have over 40 years of history building products") is None
    assert matching.years_required("No experience requirement listed") is None


def test_keyword_match_ranks_good_jd_higher():
    prof = matching.ResumeProfile.from_text(RESUME, ["airflow", "snowflake"])
    good = ("AI Engineer: build LLM agents with LangGraph and LangChain, RAG with Pinecone, evals and "
            "guardrails, Python, FastAPI, Docker, CI/CD on AWS Bedrock, SQL, PySpark, MLflow monitoring.")
    bad = ("ML Engineer: computer vision with OpenCV, C++, CUDA, Kubernetes, TypeScript, React, Go, Scala, "
           "Terraform, GCP Vertex, Java.")
    g, gm, gx = matching.keyword_match(good, prof)
    b, bm, bx = matching.keyword_match(bad, prof)
    assert g >= 85, (g, gx)
    assert b <= 35, (b, bm)


def test_clean_text_double_escaped_html():
    raw = "&lt;p&gt;Build &amp;amp; ship &lt;b&gt;LLM&lt;/b&gt; apps&lt;/p&gt;"
    assert matching.clean_text(raw) == "Build & ship LLM apps"


# ----------------------------- fetchers (mocked HTTP) ----------------------
NOW = datetime.now(timezone.utc)
ISO = (NOW - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S-04:00")


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


def patch_json(monkeypatch, mapping):
    async def fake(session, url, *, method="GET", payload=None, retries=2):
        for key, val in mapping.items():
            if key in url:
                return val(payload) if callable(val) else val
        return None
    monkeypatch.setattr(fetchers, "_get_json", fake)


def test_greenhouse(monkeypatch):
    patch_json(monkeypatch, {
        "/jobs/123": {"content": "&lt;p&gt;Python LLM agents&lt;/p&gt;"},
        "/boards/acme/jobs": {"jobs": [{"id": 123, "title": "AI Engineer", "company_name": "Acme",
                                        "location": {"name": "Austin, TX"}, "absolute_url": "https://x/123",
                                        "first_published": ISO, "updated_at": ISO}]},
    })
    posts = run(fetchers.list_greenhouse(None, "acme"))
    assert posts[0].company == "Acme" and posts[0].posted_at and posts[0].location == "Austin, TX"
    assert run(fetchers.fetch_description(None, posts[0])) == "Python LLM agents"


def test_lever(monkeypatch):
    patch_json(monkeypatch, {"api.lever.co": [{
        "id": "abc", "text": "Machine Learning Engineer", "createdAt": int(NOW.timestamp() * 1000),
        "categories": {"location": "Remote - US", "allLocations": ["Remote - US"]},
        "hostedUrl": "https://jobs.lever.co/acme/abc", "descriptionPlain": "We build RAG.",
        "lists": [{"text": "Requirements", "content": "<li>3+ years Python</li>"}], "country": "US"}]})
    p = run(fetchers.list_lever(None, "acme"))[0]
    assert "RAG" in p.description and "3+ years Python" in p.description and p.country == "US"


def test_ashby(monkeypatch):
    patch_json(monkeypatch, {"ashbyhq.com": {"jobs": [{
        "id": "j1", "title": "Applied AI Engineer", "location": "New York", "isRemote": True,
        "publishedAt": ISO, "jobUrl": "https://jobs.ashbyhq.com/acme/j1", "descriptionPlain": "LangGraph",
        "secondaryLocations": [{"location": "San Francisco"}], "isListed": True,
        "compensation": {"compensationTierSummary": "$150K - $200K"}}]}})
    p = run(fetchers.list_ashby(None, "acme"))[0]
    assert "San Francisco" in p.location and "Remote" in p.location and p.extra["comp"] == "$150K - $200K"


def test_smartrecruiters(monkeypatch):
    patch_json(monkeypatch, {
        "/postings/777": {"jobAd": {"sections": {"jobDescription": {"text": "<p>Build agents</p>"},
                                                 "qualifications": {"text": "<p>Python</p>"}}}},
        "/postings?limit": {"totalFound": 1, "content": [{
            "id": "777", "name": "AI Engineer", "releasedDate": ISO, "company": {"name": "Acme"},
            "location": {"city": "Dallas", "region": "TX", "country": "us", "remote": False}}]},
    })
    p = run(fetchers.list_smartrecruiters(None, "acme"))[0]
    assert p.location.startswith("Dallas") and p.company == "Acme"
    assert "Build agents" in run(fetchers.fetch_description(None, p))


def test_workday(monkeypatch):
    def jobs(payload):
        return {"jobPostings": [{"title": "AI Engineer", "externalPath": "/job/Plano-TX/AI-Engineer_R123",
                                 "locationsText": "Plano, TX", "postedOn": "Posted Today"}]}
    patch_json(monkeypatch, {
        "/wday/cxs/acme/ext/job/": {"jobPostingInfo": {"jobDescription": "<p>RAG &amp; agents</p>",
                                                       "externalUrl": "https://acme.wd5.myworkdayjobs.com/ext/job/x",
                                                       "country": {"descriptor": "United States of America"}}},
        "/wday/cxs/acme/ext/jobs": jobs,
    })
    posts = run(fetchers.list_workday(None, "acme|wd5|ext|Acme Corp"))
    assert len(posts) == 1 and posts[0].company == "Acme Corp" and posts[0].posted_at
    d = run(fetchers.fetch_description(None, posts[0]))
    assert d == "RAG & agents" and posts[0].country == "United States of America"


# ----------------------------- extended -----------------------------------
from jobscan import extended


def test_sitemap_and_jsonld():
    idx = ('<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           '<sitemap><loc>https://c.example.com/jobs-sitemap.xml</loc></sitemap></sitemapindex>')
    kids, urls = extended._parse_sitemap(idx)
    assert kids == ["https://c.example.com/jobs-sitemap.xml"] and urls == []
    sm = ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
          '<url><loc>https://c.example.com/jobs/123-ai-engineer</loc><lastmod>2026-10-27</lastmod></url>'
          '<url><loc>https://c.example.com/about</loc></url></urlset>')
    _, urls = extended._parse_sitemap(sm)
    job_urls = [u for u, _ in urls if extended._JOBLIKE.search(u.split(".com")[1])]
    assert job_urls == ["https://c.example.com/jobs/123-ai-engineer"]
    page = ('<html><script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting",'
            '"title":"AI Engineer","datePosted":"2026-10-27","description":"&lt;p&gt;Build RAG&lt;/p&gt;",'
            '"hiringOrganization":{"name":"Example"},"jobLocation":{"address":{"addressLocality":"Dallas",'
            '"addressRegion":"TX","addressCountry":"US"}}}</script></html>')
    jp = extended._jobposting_from_html(page)
    loc, country = extended._ld_location(jp)
    assert jp["title"] == "AI Engineer" and loc == "Dallas, TX, US" and country == "US"


def test_ai_intensity_gate():
    assert matching.ai_intensity("Build LLM agents with LangGraph, RAG, evals, vector search, PyTorch") >= 4
    assert matching.ai_intensity("Build payment APIs in Java, React and Postgres") == 0


def test_silent_sponsorship_is_kept():
    jd = "AI Engineer. Python, LLMs, RAG. Equal opportunity employer, without regard to citizenship status."
    assert matching.disqualifiers(jd) == []
    assert matching.disqualifiers("Sponsorship is available for this role.") == []


# ----------------------------- new filters ---------------------------------
@pytest.mark.parametrize("title", [
    "Visual Generation ML Engineer Graduate (AML-Ark-US) - 2027 Start",
    "Lab Automation & AI Engineering Co-Op",
    "LLM/AI Ops Development Engineer Graduate (Data Center Networking) - 2027 Start",
    "Machine Learning Engineer Intern",
    "AI Engineer, Early Career",
])
def test_student_titles(title):
    assert matching.student_role(title, "")


def test_student_from_description():
    assert matching.student_role("AI Engineer", "Must be a currently enrolled student pursuing a degree.")
    assert not matching.student_role("AI Engineer", "5+ years building production LLM systems.")


@pytest.mark.parametrize("title,ok", [
    ("LLM AIOps Development Engineer - Data Center Networking", False),
    ("Cybersecurity Engineer - AI Agent - Local Candidate", False),
    ("Lab Automation & AI Engineering Co-Op", False),
    ("Software Engineer, AI Agent", False),   # generic title, handled by the JD check
    ("AI Engineer, Internal Tools", True),
])
def test_new_title_excludes(title, ok):
    import yaml
    cfg = yaml.safe_load(open("config.yaml"))
    inc = matching.compile_patterns(cfg["title_include"])
    exc = matching.compile_patterns(cfg["title_exclude"])
    assert matching.title_ok(title, inc, exc) is ok


@pytest.mark.parametrize("loc,ok", [
    ("Global Remote", False),
    ("Worldwide", False),
    ("Remote - US", True),
    ("Valencia, Spain", False),
    ("Landshut, Germany", False),
    ("Remote", True),
])
def test_more_locations(loc, ok):
    assert matching.is_us_location(loc, None) is ok


def test_description_location():
    assert not matching.description_location_ok("Remote", "Only applicants living in British Columbia will be considered. Salary $85,000 CAD")
    assert not matching.description_location_ok("Remote", "You must be based in Canada. Pay: 90,000 CAD")
    assert matching.description_location_ok("Remote", "This role is remote within the United States.")
    assert matching.description_location_ok("Remote", "We build LLM agents.")
    assert matching.description_location_ok("Austin, TX", "Fluent in Spanish preferred")


def test_off_domains():
    net = "Deep understanding of BGP/OSPF, EVPN/VXLAN and spine-leaf fabrics. Experience with RAG and LLM agents."
    assert "networking" in matching.off_domains(net)
    java = "Proficient in Java/J2EE and Spring Boot, JUnit testing."
    assert "Java / Spring" in matching.off_domains(java)
    ok = "Build LLM agents with LangGraph, RAG, Python, FastAPI, evals on AWS."
    assert matching.off_domains(ok) == []


def test_dedupe_key():
    a = matching.dedupe_key("TikTok", "LLM AIOps Development Engineer - Data Center Networking")
    b = matching.dedupe_key("ByteDance", "LLM AIOps Development Engineer - Data Center Networking")
    assert a == b
    c = matching.dedupe_key("Acme Inc", "Machine Learning Engineer - San Jose")
    d = matching.dedupe_key("Acme", "Machine Learning Engineer - Seattle, WA")
    assert c == d
    assert matching.dedupe_key("Acme", "ML Engineer, Ads") != matching.dedupe_key("Acme", "ML Engineer, Search")


def test_format_posted():
    from jobscan.scanner import format_posted
    now = datetime(2026, 10, 28, 20, 0, tzinfo=timezone.utc)
    assert format_posted(datetime(2026, 10, 28, 17, 14, tzinfo=timezone.utc), now) == "Oct 28, 12:14 PM CT (2h ago)"
    assert format_posted(datetime(2026, 10, 27, 0, 0, tzinfo=timezone.utc), now) == "Oct 26 (44h ago)"
    assert "not listed" in format_posted(None, now)
