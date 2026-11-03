"""Job boards that list jobs from many companies: LinkedIn, Built In, Hiring Cafe, Jobright.

These catch companies that aren't in the companies/*.txt lists. Every job they return goes
through the same title / location / sponsorship / domain filters as company career sites.

- LinkedIn: LinkedIn's public (logged-out) job search pages. Free, runs every scan.
- Built In, Hiring Cafe, Jobright: Apify Actors, run once a day. Needs the APIFY_TOKEN secret.
  Spending stays inside Apify's free monthly credit: each Actor run has a hard cost cap, and
  the Apify sources are skipped when this month's usage reaches `monthly_budget_usd`.
  On Apify's free plan nothing is ever charged to you; runs simply stop when credit runs out.

Any source that fails (blocked, timed out, no token) is skipped quietly; the scan goes on.
"""
from __future__ import annotations

import asyncio
import html
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import aiohttp

from .fetchers import Posting
from .matching import clean_text

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}


def _dt(value) -> datetime | None:
    if not value:
        return None
    try:
        s = str(value).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# LinkedIn (public job search, no login)
# ---------------------------------------------------------------------------
_LI_SEARCH = ("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
              "?keywords={q}&location=United%20States&geoId=103644278&f_TPR=r{secs}&f_JT=F&f_E=2%2C3%2C4&start={start}")
_LI_JOB = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"
_LI_CARD = re.compile(r"<li>(.*?)</li>", re.DOTALL)
_LI_ID = re.compile(r"urn:li:jobPosting:(\d+)")
_LI_TITLE = re.compile(r'class="base-search-card__title"[^>]*>\s*(.*?)\s*</h3>', re.DOTALL)
_LI_COMPANY = re.compile(r'class="base-search-card__subtitle"[^>]*>\s*(?:<a[^>]*>)?\s*(.*?)\s*(?:</a>)?\s*</h4>', re.DOTALL)
_LI_LOC = re.compile(r'class="job-search-card__location"[^>]*>\s*(.*?)\s*</span>', re.DOTALL)
_LI_TIME = re.compile(r'<time[^>]*datetime="([0-9-]+)"')
_LI_DESC = re.compile(r'class="show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>', re.DOTALL)


def _txt(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", s or "")).strip()


def parse_linkedin(page: str) -> list[Posting]:
    out = []
    for card in _LI_CARD.findall(page or ""):
        m = _LI_ID.search(card)
        t = _LI_TITLE.search(card)
        if not (m and t):
            continue
        c, loc, tm = _LI_COMPANY.search(card), _LI_LOC.search(card), _LI_TIME.search(card)
        jid = m.group(1)
        out.append(Posting(
            source="linkedin", company=_txt(c.group(1)) if c else "", slug="linkedin", job_id=jid,
            title=_txt(t.group(1)), location=_txt(loc.group(1)) if loc else "",
            url=f"https://www.linkedin.com/jobs/view/{jid}", posted_at=_dt(tm.group(1)) if tm else None))
    return out


async def linkedin_search(session: aiohttp.ClientSession, queries: list[str], hours: int,
                          pages: int = 6) -> list[Posting]:
    found: dict[str, Posting] = {}
    for q in queries:
        for page in range(pages):
            url = _LI_SEARCH.format(q=quote_plus(q), secs=hours * 3600, start=page * 10)
            try:
                async with session.get(url, headers=UA, timeout=aiohttp.ClientTimeout(total=20)) as r:
                    if r.status != 200:
                        break  # 429 / 999 = rate limited; move on
                    posts = parse_linkedin(await r.text())
            except Exception:  # noqa: BLE001
                break
            if not posts:
                break
            for p in posts:
                found.setdefault(p.job_id, p)
            await asyncio.sleep(1.0)
    return list(found.values())


async def linkedin_description(session: aiohttp.ClientSession, p: Posting) -> str:
    for attempt in range(2):
        try:
            async with session.get(_LI_JOB.format(id=p.job_id), headers=UA,
                                   timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status == 429:
                    await asyncio.sleep(5 * (attempt + 1))
                    continue
                if r.status != 200:
                    return ""
                m = _LI_DESC.search(await r.text())
                return clean_text(m.group(1)) if m else ""
        except Exception:  # noqa: BLE001
            return ""
    return ""


# ---------------------------------------------------------------------------
# Apify Actors (Built In, Hiring Cafe, Jobright)
# ---------------------------------------------------------------------------
APIFY = "https://api.apify.com/v2"


async def apify_month_usage(session: aiohttp.ClientSession, token: str) -> float | None:
    try:
        async with session.get(f"{APIFY}/users/me/limits", params={"token": token},
                               timeout=aiohttp.ClientTimeout(total=20)) as r:
            data = (await r.json()).get("data", {})
        return float(data.get("current", {}).get("monthlyUsageUsd", 0.0))
    except Exception:  # noqa: BLE001
        return None


async def apify_run(session: aiohttp.ClientSession, token: str, actor: str, payload: dict,
                    max_usd: float) -> list[dict]:
    url = f"{APIFY}/acts/{actor.replace('/', '~')}/run-sync-get-dataset-items"
    params = {"token": token, "maxTotalChargeUsd": str(max_usd), "timeout": "280", "clean": "true"}
    try:
        async with session.post(url, params=params, json=payload,
                                timeout=aiohttp.ClientTimeout(total=320)) as r:
            if r.status not in (200, 201):
                print(f"  Apify {actor}: HTTP {r.status} {(await r.text())[:150]}")
                return []
            items = await r.json()
            return items if isinstance(items, list) else []
    except Exception as e:  # noqa: BLE001
        print(f"  Apify {actor}: {e}")
        return []


def _g(d: dict, path: str, default=None):
    for k in path.split("."):
        if not isinstance(d, dict):
            return default
        d = d.get(k)
    return default if d is None else d


def map_builtin(items: list[dict]) -> list[Posting]:
    out = []
    for it in items:
        if not it.get("jobId") or not it.get("title"):
            continue
        out.append(Posting(
            source="builtin", company=it.get("company", ""), slug="builtin", job_id=str(it["jobId"]),
            title=it["title"], location=it.get("location", ""), url=it.get("jobUrl", ""),
            posted_at=_dt(it.get("postedDate")), country=None,
            description=clean_text(it.get("description") or it.get("descriptionHtml") or ""),
            extra={"comp": it.get("salaryText") or ""}))
    return out


def map_hiringcafe(items: list[dict]) -> list[Posting]:
    out = []
    for it in items:
        v5 = it.get("v5_processed_job_data") or {}
        title = _g(it, "job_information.title") or v5.get("core_job_title")
        if not it.get("id") or not title:
            continue
        lo, hi = v5.get("yearly_min_compensation"), v5.get("yearly_max_compensation")
        comp = f"${lo // 1000}K-${hi // 1000}K" if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) else ""
        desc = _g(it, "job_information.descriptionText") or _g(it, "job_information.description") or ""
        out.append(Posting(
            source="hiringcafe", company=v5.get("company_name") or _g(it, "enriched_company_data.name", ""),
            slug="hiringcafe", job_id=str(it["id"])[-60:], title=title,
            location=v5.get("formatted_workplace_location") or "", url=it.get("apply_url") or "",
            posted_at=_dt(v5.get("estimated_publish_date")), description=clean_text(desc), extra={"comp": comp}))
    return out


def map_jobright(items: list[dict]) -> list[Posting]:
    out = []
    for it in items:
        if not it.get("id") or not it.get("title"):
            continue
        if it.get("isCitizenOnly") or it.get("isClearanceRequired"):
            continue  # Jobright already knows these rule you out
        title = re.sub(r"\s+Job Details\s*\|.*$", "", it["title"]).strip()
        parts = [it.get("description") or ""] + [str(x) for x in (it.get("requirements") or [])] \
            + [str(x) for x in (it.get("responsibilities") or [])]
        out.append(Posting(
            source="jobright", company=it.get("companyName", ""), slug="jobright", job_id=str(it["id"]),
            title=title, location=it.get("location", ""), url=it.get("url", ""),
            posted_at=_dt(it.get("postedAt")), description=clean_text("\n".join(parts)),
            extra={"comp": it.get("salary") or "",
                   "h1b": "H-1B sponsor" if it.get("isH1bSponsor") else ""}))
    return out


def map_dice(items: list[dict]) -> list[Posting]:
    out = []
    for it in items:
        if not it.get("id") or not it.get("title") or it.get("isRepost") or it.get("isExpired"):
            continue
        loc = it.get("location") or ", ".join(x for x in (it.get("city"), it.get("state")) if x)
        out.append(Posting(
            source="dice", company=it.get("company") or "", slug="dice", job_id=str(it["id"]),
            title=it["title"], location=loc or ("Remote" if it.get("remote") else ""),
            url=it.get("url") or it.get("applyUrl") or "", posted_at=_dt(it.get("postedDate")),
            description=clean_text(it.get("description_text") or it.get("description_html") or ""),
            extra={"comp": it.get("payRate") or "",
                   "h1b": "Willing to sponsor" if it.get("willingToSponsor") else ""}))
    return out


async def apify_sources(session: aiohttp.ClientSession, cfg: dict) -> dict[str, list[Posting]]:
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token:
        return {}
    budget = float(cfg.get("monthly_budget_usd", 4.5))
    used = await apify_month_usage(session, token)
    if used is None or used >= budget:
        print(f"Apify job boards skipped (this month's usage: {used}, budget {budget}).")
        return {}
    cap = float(cfg.get("per_actor_max_usd", 0.06))
    days = str(cfg.get("posted_within_days", 1))
    tasks = {
        "builtin": apify_run(session, token, "solidcode/builtin-scraper", {
            "searchQueries": cfg.get("builtin_queries", ["machine learning engineer"]),
            "category": "ai-machine-learning", "experienceLevel": "mid-level", "location": "United States",
            "postedWithinDays": days, "maxResultsPerQuery": 25, "fetchDescription": True}, cap),
        "hiringcafe": apify_run(session, token, "memo23/apify-hiring-cafe-scraper", {
            "keyword": cfg.get("hiringcafe_keyword", "AI engineer machine learning engineer"),
            "location": "United States", "dateFetchedPastNDays": int(days), "sortBy": "date",
            "seniorityLevels": ["Mid Level"], "commitmentTypes": ["Full Time"],
            "maxItems": int(cfg.get("hiringcafe_max", 30)), "enrichDescription": True}, cap),
        "jobright": apify_run(session, token, "silentflow/jobright-scraper", {
            "searchQueries": cfg.get("jobright_queries", ["AI engineer", "machine learning engineer"]),
            "country": "us", "datePosted": "24h", "experienceLevel": ["entry", "mid"],
            "jobTypes": ["full_time"], "maxItems": int(cfg.get("jobright_max", 20))}, cap),
        "dice": apify_run(session, token, "memo23/apify-dice-scraper", {
            "keywords": cfg.get("dice_queries", ["AI engineer", "machine learning engineer"]),
            "location": "United States", "countryCode": "US", "postedDate": "ONE",
            "employmentType": ["FULLTIME"], "skipReposts": True,
            "maxItems": int(cfg.get("dice_max", 30))}, cap),
    }
    results = await asyncio.gather(*tasks.values())
    mappers = {"builtin": map_builtin, "hiringcafe": map_hiringcafe, "jobright": map_jobright, "dice": map_dice}
    return {name: mappers[name](items) for name, items in zip(tasks, results)}


# ---------------------------------------------------------------------------
# Hacker News "Ask HN: Who is hiring?" (monthly thread, free public API)
# ---------------------------------------------------------------------------
HN_API = "https://hn.algolia.com/api/v1"
_HN_ROLE = re.compile(r"\b(ai|ml|machine learning|llm|genai|generative ai|applied (ai|ml)|mlops|"
                      r"forward deployed|data scientist)\b", re.I)
_HN_VISA = re.compile(r"\bvisas?\b", re.I)
_HN_NO_VISA = re.compile(r"\b(no|not|without)\b[^|\n]{0,20}\bvisas?\b|\bvisas?\b[^|\n]{0,20}\b(not|no)\b", re.I)


def parse_hn_comment(c: dict) -> Posting | None:
    """One top-level comment -> Posting. HN posts start with 'Company | Role | Location | ...'."""
    raw = c.get("text") or ""
    if not raw or not c.get("id"):
        return None
    head = clean_text(re.split(r"(?i)<p>", raw, maxsplit=1)[0])
    parts = [s.strip() for s in head.split("|") if s.strip()]
    if len(parts) < 2:
        return None
    company = re.sub(r"\s*\(.*?\)\s*$", "", parts[0])[:80]
    rest = parts[1:]
    role = next((s for s in rest if _HN_ROLE.search(s) and re.search(r"(?i)engineer|scientist|developer|ml|ai", s)),
                None)
    if not role:
        return None
    loc_bits = [s for s in rest if s is not role and (re.search(r"(?i)remote|onsite|on-site|hybrid", s)
                                                      or re.search(r",\s*[A-Z]{2}\b", s)
                                                      or re.search(r"(?i)\b(usa?|united states|new york|nyc|"
                                                                   r"san francisco|sf|bay area|seattle|austin|boston|"
                                                                   r"chicago|dallas|los angeles|denver)\b", s))]
    location = "; ".join(loc_bits)[:200]
    visa = "visa sponsorship mentioned" if _HN_VISA.search(head) and not _HN_NO_VISA.search(head) else ""
    return Posting(
        source="hackernews", company=company, slug="hackernews", job_id=str(c["id"]),
        title=role[:150], location=location, url=f"https://news.ycombinator.com/item?id={c['id']}",
        posted_at=_dt(c.get("created_at")), description=clean_text(raw), extra={"comp": "", "h1b": visa})


async def hn_whos_hiring(session: aiohttp.ClientSession) -> list[Posting]:
    try:
        async with session.get(f"{HN_API}/search_by_date",
                               params={"tags": "story,author_whoishiring", "hitsPerPage": "10"},
                               timeout=aiohttp.ClientTimeout(total=20)) as r:
            hits = (await r.json()).get("hits", [])
        story = next((h for h in hits if "who is hiring" in (h.get("title") or "").lower()), None)
        if not story:
            return []
        async with session.get(f"{HN_API}/items/{story['objectID']}",
                               timeout=aiohttp.ClientTimeout(total=60)) as r:
            thread = await r.json()
    except Exception as e:  # noqa: BLE001
        print(f"  Hacker News: {e}")
        return []
    out = []
    for c in thread.get("children") or []:
        p = parse_hn_comment(c)
        if p:
            out.append(p)
    return out


# ---------------------------------------------------------------------------
# VC portfolio job boards (most run on Getro). Best effort: a board that can't be read is skipped.
# ---------------------------------------------------------------------------
GETRO_API = "https://api.getro.com/api/v2/collections/{cid}/search/jobs"
_GETRO_ID = re.compile(r'"(?:collectionId|collection_id)"\s*:\s*"?(\d+)|"network"\s*:\s*\{\s*"id"\s*:\s*"?(\d+)')


def map_getro(board: str, jobs: list[dict]) -> list[Posting]:
    out = []
    for j in jobs:
        title, url = j.get("title"), j.get("url") or j.get("apply_url")
        if not title or not url:
            continue
        org = j.get("organization") or {}
        locs = j.get("locations") or j.get("searchable_locations") or []
        location = "; ".join(x if isinstance(x, str) else (x.get("name") or "") for x in locs)
        if not location and (j.get("work_mode") or "").lower() == "remote":
            location = "Remote"
        ts = j.get("created_at") or j.get("posted_at")
        posted = (datetime.fromtimestamp(ts, tz=timezone.utc) if isinstance(ts, (int, float))
                  else _dt(ts))
        out.append(Posting(
            source="vcboards", company=org.get("name") or j.get("company_name") or "", slug=f"vc-{board}",
            job_id=str(j.get("id") or j.get("slug") or url)[-80:], title=title, location=location, url=url,
            posted_at=posted, description=clean_text(j.get("description") or ""),
            extra={"comp": "", "board": board}))
    return out


async def getro_board(session: aiohttp.ClientSession, name: str, base: str, queries: list[str],
                      per_query: int = 40) -> list[Posting]:
    try:
        async with session.get(base.rstrip("/") + "/jobs", headers=UA,
                               timeout=aiohttp.ClientTimeout(total=20)) as r:
            m = _GETRO_ID.search(await r.text())
        if not m:
            print(f"  VC board {name}: not a Getro board, skipped")
            return []
        cid = m.group(1) or m.group(2)
        found: dict[str, Posting] = {}
        for q in queries:
            body = {"hitsPerPage": per_query, "page": 0, "query": q, "filters": ""}
            async with session.post(GETRO_API.format(cid=cid), json=body, headers=UA,
                                    timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status != 200:
                    print(f"  VC board {name}: HTTP {r.status}")
                    break
                data = await r.json()
            jobs = (data.get("results") or {}).get("jobs") or data.get("jobs") or []
            for p in map_getro(name, jobs):
                found.setdefault(p.job_id, p)
        return list(found.values())
    except Exception as e:  # noqa: BLE001
        print(f"  VC board {name}: {e}")
        return []


_SCRIPT_RE = re.compile(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>")


async def page_text(session: aiohttp.ClientSession, url: str) -> str:
    """Plain text of a job page (used when a board gives no description)."""
    try:
        async with session.get(url, headers=UA, timeout=aiohttp.ClientTimeout(total=20)) as r:
            if r.status != 200:
                return ""
            body = await r.text()
    except Exception:  # noqa: BLE001
        return ""
    return clean_text(_SCRIPT_RE.sub(" ", body))[:20000]


async def vc_boards(session: aiohttp.ClientSession, cfg: dict) -> list[Posting]:
    queries = cfg.get("queries", ["machine learning engineer", "AI engineer"])
    sem = asyncio.Semaphore(4)

    async def one(name, url):
        async with sem:
            return await getro_board(session, name, url, queries)
    results = await asyncio.gather(*(one(n, u) for n, u in (cfg.get("boards") or {}).items()))
    return [p for r in results for p in r]


def apify_due(cfg: dict, now: datetime) -> bool:
    """Apify sources run in one scan a day (the scan whose UTC hour is listed)."""
    return now.astimezone(timezone.utc).hour in set(cfg.get("run_hours_utc", [15, 16]))


async def fetch_all(session: aiohttp.ClientSession, cfg: dict, now: datetime, lookback_hours: int,
                    force_apify: bool = False) -> dict[str, list[Posting]]:
    out: dict[str, list[Posting]] = {}
    li = cfg.get("linkedin", {}) or {}
    if li.get("enabled", True):
        out["linkedin"] = await linkedin_search(session, li.get("queries", []), lookback_hours,
                                                pages=int(li.get("pages", 6)))
    hn = cfg.get("hackernews", {}) or {}
    if hn.get("enabled", False):
        out["hackernews"] = await hn_whos_hiring(session)
    vc = cfg.get("vc_boards", {}) or {}
    if vc.get("enabled", False):
        out["vcboards"] = await vc_boards(session, vc)
    ap = cfg.get("apify", {}) or {}
    if ap.get("enabled", True) and (force_apify or apify_due(ap, now)):
        out.update(await apify_sources(session, ap))
    return out
