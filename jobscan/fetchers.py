"""Async fetchers for company career sites (Greenhouse, Lever, Ashby, SmartRecruiters, Workday).

Each `list_*` function returns lightweight `Posting`s for one company. Descriptions are
included when the listing API provides them; otherwise `fetch_description` fills them in
later, only for postings that survive the cheap title/location/date filters.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import aiohttp

from .matching import clean_text

UA = {"User-Agent": "Mozilla/5.0 (job-scanner; personal job alerts)", "Accept": "application/json"}


@dataclass
class Posting:
    source: str
    company: str
    slug: str
    job_id: str
    title: str
    location: str
    url: str
    posted_at: datetime | None
    country: str | None = None
    description: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def uid(self) -> str:
        return f"{self.source}:{self.slug}:{self.job_id}"


def _iso(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):  # epoch ms
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    try:
        s = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


async def _get_json(session: aiohttp.ClientSession, url: str, *, method="GET", payload=None, retries=2):
    for attempt in range(retries + 1):
        try:
            async with session.request(method, url, json=payload, headers=UA) as r:
                if r.status == 404:
                    return None
                if r.status == 429 or r.status >= 500:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                if r.status != 200:
                    return None
                return await r.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            if attempt == retries:
                return None
            await asyncio.sleep(1 + attempt)
    return None


def _pretty(slug: str) -> str:
    return re.sub(r"[-_]+", " ", slug).strip().title()


# ---------------------------------------------------------------------------
# Greenhouse
# ---------------------------------------------------------------------------
async def list_greenhouse(session, slug: str) -> list[Posting]:
    data = await _get_json(session, f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    out = []
    for j in (data or {}).get("jobs", []) or []:
        out.append(Posting(
            source="greenhouse", slug=slug, company=j.get("company_name") or _pretty(slug),
            job_id=str(j.get("id")), title=j.get("title") or "",
            location=((j.get("location") or {}).get("name") or ""),
            url=j.get("absolute_url") or "",
            posted_at=_iso(j.get("first_published")) or _iso(j.get("updated_at")),
        ))
    return out


async def desc_greenhouse(session, p: Posting) -> str:
    d = await _get_json(session, f"https://boards-api.greenhouse.io/v1/boards/{p.slug}/jobs/{p.job_id}")
    return clean_text((d or {}).get("content"))


# ---------------------------------------------------------------------------
# Lever
# ---------------------------------------------------------------------------
async def list_lever(session, slug: str) -> list[Posting]:
    data = await _get_json(session, f"https://api.lever.co/v0/postings/{slug}?mode=json")
    out = []
    for j in data or []:
        if not isinstance(j, dict):
            continue
        cats = j.get("categories") or {}
        locs = cats.get("allLocations") or [cats.get("location") or ""]
        parts = [j.get("descriptionPlain") or clean_text(j.get("description"))]
        for lst in j.get("lists") or []:
            parts.append(f"{lst.get('text', '')}: {clean_text(lst.get('content'))}")
        parts.append(j.get("additionalPlain") or clean_text(j.get("additional")))
        out.append(Posting(
            source="lever", slug=slug, company=_pretty(slug), job_id=str(j.get("id")),
            title=j.get("text") or "", location=" / ".join(x for x in locs if x),
            url=j.get("hostedUrl") or j.get("applyUrl") or "",
            posted_at=_iso(j.get("createdAt")), country=j.get("country"),
            description=" ".join(x for x in parts if x),
            extra={"workplace": j.get("workplaceType")},
        ))
    return out


# ---------------------------------------------------------------------------
# Ashby
# ---------------------------------------------------------------------------
async def list_ashby(session, slug: str) -> list[Posting]:
    data = await _get_json(session, f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true")
    out = []
    for j in (data or {}).get("jobs", []) or []:
        if j.get("isListed") is False:
            continue
        locs = [j.get("location") or ""] + [s.get("location", "") for s in j.get("secondaryLocations") or []]
        if j.get("isRemote"):
            locs.append("Remote")
        countries = [((x.get("address") or {}).get("postalAddress") or {}).get("addressCountry")
                     for x in [j] + list(j.get("secondaryLocations") or [])]
        countries = [c for c in countries if c]
        us_like = [c for c in countries if c.strip().lower() in {"us", "usa", "united states", "united states of america"}]
        # Multi-country postings: if any location is in the US, treat it as US.
        country = us_like[0] if us_like else (countries[0] if countries else None)
        comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
        out.append(Posting(
            source="ashby", slug=slug, company=_pretty(slug), job_id=str(j.get("id")),
            title=j.get("title") or "", location=" / ".join(x for x in locs if x),
            url=j.get("jobUrl") or j.get("applyUrl") or "",
            posted_at=_iso(j.get("publishedAt")), country=country,
            description=j.get("descriptionPlain") or clean_text(j.get("descriptionHtml")),
            extra={"comp": comp},
        ))
    return out


# ---------------------------------------------------------------------------
# SmartRecruiters
# ---------------------------------------------------------------------------
async def list_smartrecruiters(session, slug: str) -> list[Posting]:
    out, offset = [], 0
    while offset < 1000:
        data = await _get_json(session, f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset={offset}")
        items = (data or {}).get("content") or []
        for j in items:
            loc = j.get("location") or {}
            loc_str = loc.get("fullLocation") or ", ".join(
                x for x in [loc.get("city"), loc.get("region"), (loc.get("country") or "").upper()] if x)
            if loc.get("remote"):
                loc_str += " (Remote)"
            out.append(Posting(
                source="smartrecruiters", slug=slug,
                company=((j.get("company") or {}).get("name") or _pretty(slug)),
                job_id=str(j.get("id")), title=j.get("name") or "", location=loc_str,
                url=f"https://jobs.smartrecruiters.com/{slug}/{j.get('id')}",
                posted_at=_iso(j.get("releasedDate")), country=(loc.get("country") or None),
            ))
        total = (data or {}).get("totalFound") or 0
        offset += 100
        if not items or offset >= total:
            break
    return out


async def desc_smartrecruiters(session, p: Posting) -> str:
    d = await _get_json(session, f"https://api.smartrecruiters.com/v1/companies/{p.slug}/postings/{p.job_id}")
    secs = (((d or {}).get("jobAd") or {}).get("sections") or {})
    return " ".join(clean_text((secs.get(k) or {}).get("text")) for k in
                    ("jobDescription", "qualifications", "additionalInformation", "companyDescription"))


# ---------------------------------------------------------------------------
# Workday (reads every posting; descriptions fetched later for the ones that pass filters)
# ---------------------------------------------------------------------------
WORKDAY_FULL_LIST_CAP = 2000
WORKDAY_QUERIES = ["machine learning", "AI engineer", "artificial intelligence", "generative AI", "LLM",
                   "data scientist", "software engineer AI"]
_POSTED_RE = re.compile(r"posted\s+(today|yesterday|(\d+)\+?\s+days?\s+ago)", re.IGNORECASE)


def _workday_posted(text: str) -> datetime | None:
    m = _POSTED_RE.search(text or "")
    if not m:
        return None
    now = datetime.now(timezone.utc)
    word = m.group(1).lower()
    if word == "today":
        return now
    if word == "yesterday":
        return now - timedelta(days=1)
    return now - timedelta(days=int(m.group(2)))


async def list_workday(session, entry: str) -> list[Posting]:
    tenant, wd, site, name = (entry.split("|") + ["", "", "", ""])[:4]
    base = f"https://{tenant}.{wd}.myworkdayjobs.com"
    api = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    seen, out = set(), []

    async def page_through(query: str, max_jobs: int) -> tuple[list[dict], int | None]:
        rows, total = [], None
        for offset in range(0, max_jobs, 20):
            data = await _get_json(session, api, method="POST",
                                   payload={"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": query})
            if data is None:
                return rows, (None if offset == 0 else total)
            if offset == 0:
                total = int(data.get("total") or 0)
            page = data.get("jobPostings") or []
            rows += page
            if len(page) < 20 or offset + 20 >= (total or 0):
                break
        return rows, total

    # 1) Read the whole catalogue (every job, every title). Workday stops paging
    #    around 2,000 results, so for the few giant employers we also run AI/ML
    #    searches to make sure relevant jobs past that point are still found.
    rows, total = await page_through("", WORKDAY_FULL_LIST_CAP)
    if total is None:
        return []  # dead tenant/site
    if total > WORKDAY_FULL_LIST_CAP:
        for q in WORKDAY_QUERIES:
            more, _ = await page_through(q, 100)
            rows += more
    for j in rows:
        path = j.get("externalPath") or ""
        if not path or path in seen:
            continue
        seen.add(path)
        out.append(Posting(
            source="workday", slug=f"{tenant}/{site}", company=name or _pretty(tenant),
            job_id=path.rsplit("_", 1)[-1], title=j.get("title") or "",
            location=j.get("locationsText") or "", url=f"{base}/{site}{path}",
            posted_at=_workday_posted(j.get("postedOn") or ""),
            extra={"api_detail": f"{base}/wday/cxs/{tenant}/{site}{path}"},
        ))
    return out


async def desc_workday(session, p: Posting) -> str:
    d = await _get_json(session, p.extra.get("api_detail", ""))
    info = (d or {}).get("jobPostingInfo") or {}
    if info.get("country", {}).get("descriptor"):
        p.country = info["country"]["descriptor"]
    if info.get("location") and not p.location:
        p.location = info["location"]
    if info.get("externalUrl"):
        p.url = info["externalUrl"]
    return clean_text(info.get("jobDescription"))



# ---------------------------------------------------------------------------
# BambooHR (public careers JSON; the old embed widget no longer lists jobs)
#   list:   https://{slug}.bamboohr.com/careers/list
#   detail: https://{slug}.bamboohr.com/careers/{id}/detail  (description + datePosted)
# companies/bamboohr.txt lines look like "slug|Company Name".
# ---------------------------------------------------------------------------
def _bamboo_location(j: dict) -> tuple[str, str | None]:
    loc = j.get("location") or {}
    ats = j.get("atsLocation") or {}
    city = loc.get("city") or ats.get("city")
    state = loc.get("state") or ats.get("state") or ats.get("province")
    country = ats.get("country") or loc.get("addressCountry") or loc.get("country")
    parts = [x for x in [city, state, country] if x]
    remote = j.get("isRemote") or str(j.get("locationType", "")).lower() in {"1", "remote"}
    text = ", ".join(parts)
    if remote:
        text = (text + " / Remote").strip(" /")
    return text, country


def bamboo_postings(slug: str, name: str, data) -> list[Posting]:
    rows = (data or {}).get("result") if isinstance(data, dict) else data
    out = []
    for j in rows or []:
        if not isinstance(j, dict) or not j.get("id"):
            continue
        loc, country = _bamboo_location(j)
        out.append(Posting(
            source="bamboohr", slug=slug, company=name or _pretty(slug), job_id=str(j["id"]),
            title=j.get("jobOpeningName") or j.get("title") or "", location=loc,
            url=f"https://{slug}.bamboohr.com/careers/{j['id']}",
            posted_at=_iso(j.get("datePosted")), country=country,
        ))
    return out


async def list_bamboohr(session, entry: str) -> list[Posting]:
    slug, _, name = entry.partition("|")
    slug = slug.strip()
    data = await _get_json(session, f"https://{slug}.bamboohr.com/careers/list")
    return bamboo_postings(slug, name.strip(), data)


async def desc_bamboohr(session, p: Posting) -> str:
    data = await _get_json(session, f"https://{p.slug}.bamboohr.com/careers/{p.job_id}/detail")
    jo = ((data or {}).get("result") or {}).get("jobOpening") or {}
    if not p.posted_at:
        p.posted_at = _iso(jo.get("datePosted"))
    loc = jo.get("location") or {}
    if not p.country:
        p.country = loc.get("addressCountry") or (jo.get("atsLocation") or {}).get("country")
    return clean_text(jo.get("description"))


LISTERS = {
    "greenhouse": list_greenhouse,
    "lever": list_lever,
    "ashby": list_ashby,
    "smartrecruiters": list_smartrecruiters,
    "workday": list_workday,
    "bamboohr": list_bamboohr,
}
DESCRIBERS = {
    "greenhouse": desc_greenhouse,
    "smartrecruiters": desc_smartrecruiters,
    "workday": desc_workday,
    "bamboohr": desc_bamboohr,
}


async def fetch_description(session, p: Posting) -> str:
    if p.description:
        return p.description
    fn = DESCRIBERS.get(p.source)
    return (await fn(session, p)) if fn else ""
