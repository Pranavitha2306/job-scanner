"""Strict screening, checked against real postings that turned out to be poor fits."""
from pathlib import Path

import pytest

from jobscan import matching

FIX = Path(__file__).parent / "fixtures"


def reasons(title: str, location: str, text: str) -> list[str]:
    """Same exclusion checks the scanner runs on a full job description."""
    out = []
    if not matching.is_us_location(location) or not matching.description_location_ok(location, text):
        out.append("not US")
    out += matching.disqualifiers(text)
    for r in (matching.language_problem(title, text), matching.employment_problem(title, text),
              matching.senior_problem(text)):
        if r:
            out.append(r)
    yrs = matching.years_required(text)
    if yrs and yrs > 6:
        out.append(f"{yrs}+ years")
    out += [f"off-target: {d}" for d in matching.off_domains(f"{title} {text}")]
    return out


BAD = [
    ("ebay.txt", "AI Analytics Engineer - Traffic", "Austin, TX", "No sponsorship"),
    ("cerrowire.txt", "Data & AI Solutions Developer", "Remote - United States of America", "No sponsorship"),
    ("freelance_django.txt", "Freelance Full-Stack Developer", "United States", "not a full-time job"),
    ("truezero.txt", "AI/ML Security Specialist", "Ashburn, VA", "Federal agency"),
    ("ntt_munich.txt", "Forward Deployed Engineer (w/m/x)", "München", "German"),
    ("deloitte_de.txt", "Consultant Forward Deployed Engineering (m/w/d)", "mehrere Standorte, DE", "German"),
    ("fico_dba.txt", "Data Engineer (Python & Cloud Databases)", "Work from Home, United States", "database administration"),
    ("brightvision_architect.txt", "AI Data Platform Engineer", "Remote (U.S.)", "8+ years"),
    ("sma_voice.txt", "Voice AI Solutions Engineer", "Remote", "voice / telephony"),
    ("renesas.txt", "Cloud DevOps and AI Security Engineer", "San Jose, California", "Export control"),
    ("m3_web.txt", "Software Engineer", "Creve Coeur, MO", "off-target"),
    ("jobgether_fullstack.txt", "Full Stack Engineer, Agentic AI", "United States", "frontend / full-stack"),
    ("sensor_tower.txt", "AI Engineer", "Remote", "language"),
]


@pytest.mark.parametrize("fname,title,loc,expect", BAD)
def test_bad_postings_are_dropped(fname, title, loc, expect):
    r = reasons(title, loc, (FIX / fname).read_text())
    assert r, f"{fname} was kept"
    assert any(expect.lower() in x.lower() for x in r), f"{fname}: {r}"


@pytest.mark.parametrize("fname,title,loc", [
    ("coinflow.txt", "MLOps Engineer", "Chicago, IL"),
    ("hatch.txt", "Forward Deployed Engineer", "Remote - United States"),
    ("atlas_copco.txt", "Applied AI Engineer", "Rock Hill, SC"),
])
def test_good_postings_are_kept(fname, title, loc):
    assert reasons(title, loc, (FIX / fname).read_text()) == []


def test_full_stack_title_excluded_by_config():
    import yaml
    cfg = yaml.safe_load(open("config.yaml"))
    inc, exc = matching.compile_patterns(cfg["title_include"]), matching.compile_patterns(cfg["title_exclude"])
    assert not matching.title_ok("Full Stack Engineer, Agentic AI", inc, exc)
    assert not matching.title_ok("AI Engineer (m/w/d)", inc, exc)
    assert matching.title_ok("Applied AI Engineer", inc, exc)


def test_language_and_employment_helpers():
    assert matching.language_problem("ML Engineer", "Fluent German (C1) required.")
    assert not matching.language_problem("ML Engineer", "You will work with our team in Austin on LLM systems.")
    assert matching.employment_problem("", "This is a part-time engagement, about 60 hours per month.")
    assert not matching.employment_problem("", "Full-time, W-2 contract role in San Antonio.")


def test_peak_hours_summary():
    from jobscan import notify
    hours = {"Tue 09": 12, "Wed 10": 9, "Thu 09": 6, "Mon 14": 3}
    s = notify.peak_hours(hours)
    assert "9 AM-10 AM" in s and "Tue" in s
    assert notify.peak_hours({"Tue 09": 3}) == ""
