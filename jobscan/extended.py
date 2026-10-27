"""Extra coverage beyond the five core platforms.

1. `ats_scrapers` platforms: 20+ more careers-site systems that big employers use for their
   *own-branded* careers pages (iCIMS, Taleo, SuccessFactors, Oracle, Phenom, Eightfold,
   Avature, BambooHR, Workable, Paycom, ADP, Dayforce, UKG ...), plus first-party sites
   (Google, Apple, Uber, TikTok/ByteDance).
2. Custom careers sites: any URL you list in companies/custom.txt. We read the site's
   sitemap to find job pages, then the schema.org JobPosting data on each page (the same
   structured data that powers Google's job search, so most custom sites publish it).
"""
from __future__ import annotations

import asyncio
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urlparse

from .fetchers import Posting, _iso, _pretty
from .matching import clean_text

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}

# ---------------------------------------------------------------------------
# 1. ats_scrapers platforms
# ---------------------------------------------------------------------------
FIRST_PARTY = {"google": "Google", "apple": "Apple", "uber": "Uber", "tiktok": "TikTok", "bytedance": "ByteDance"}


def _job_to_posting(ats: str, slug: str, job) -> Posting:
    loc = job.location or ""
    if getattr(job, "is_remote", None) and "remote" not in loc.lower():
        loc = (loc + " / Remote").strip(" /")
    url = str(job.apply_url or job.url) if getattr(job, "apply_url", None) else str(job.url)
    return Posting(
        source=ats, slug=slug, company=job.company or FIRST_PARTY.get(ats) or _pretty(slug),
        job_id=str(job.ats_id or job.url), title=job.title or "", location=loc, url=str(job.url) or url,
        posted_at=job.posted_at if (job.posted_at is None or job.posted_at.tzinfo) else
        job.posted_at.replace(tzinfo=timezone.utc),
        country=getattr(job, "country_iso", None), description=clean_text(job.description or ""),
        extra={"comp": getattr(job, "salary_summary", None) or ""},
    )


async def list_library(ats: str, slug: str, *, descriptions: bool, timeout_s: float = 180) -> list[Posting]:
    from ats_scrapers.scrapers import get_scraper  # imported lazily: optional dependency
    scraper = get_scraper(ats, slug, include_descriptions=descriptions)
    jobs = await asyncio.wait_for(scraper.afetch(), timeout=timeout_s)
    return [_job_to_posting(ats, slug, j) for j in jobs or []]


async def describe_library(postings: list[Posting]) -> None:
    """Re-fetch each company that has candidates, this time with descriptions."""
    by_board: dict[tuple[str, str], list[Posting]] = {}
    for p in postings:
        if not p.description:
            by_board.setdefault((p.source, p.slug), []).append(p)
    sem = asyncio.Semaphore(8)

    async def one(key, items):
        async with sem:
            try:
                full = await list_library(key[0], key[1], descriptions=True, timeout_s=300)
            except Exception as e:  # noqa: BLE001
                print(f"  description fetch failed for {key}: {e}")
                return
        by_id = {f.job_id: f for f in full}
        by_url = {f.url: f for f in full}
        for p in items:
            f = by_id.get(p.job_id) or by_url.get(p.url)
            if f:
                p.description = f.description
                p.country = p.country or f.country
                if not p.posted_at:
                    p.posted_at = f.posted_at
    await asyncio.gather(*(one(k, v) for k, v in by_board.items()))


# ---------------------------------------------------------------------------
# 2. Custom careers sites via sitemap + schema.org JobPosting
# ---------------------------------------------------------------------------
_JOBLIKE = re.compile(r"/(jobs?|careers?|positions?|openings?|opportunit\w*|requisitions?|vacanc\w*|role)s?/[^?#]{4,}", re.I)
_LD_RE = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.I | re.S)
_TITLE_RE = re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', re.I)


async def _text(session, url: str, limit: int = 3_000_000) -> str | None:
    try:
        async with session.get(url, headers=UA, allow_redirects=True) as r:
            if r.status != 200:
                return None
            raw = await r.content.read(limit)
            return raw.decode(r.charset or "utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return None


def _parse_sitemap(xml_text: str) -> tuple[list[str], list[tuple[str, str | None]]]:
    """Return (child sitemap URLs, [(page url, lastmod)])."""
    try:
        root = ET.fromstring(xml_text.encode("utf-8", errors="ignore"))
    except ET.ParseError:
        return [], []
    ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
    if root.tag.endswith("sitemapindex"):
        return [e.findtext(f"{ns}loc", "").strip() for e in root.findall(f"{ns}sitemap")], []
    urls = [(e.findtext(f"{ns}loc", "").strip(), (e.findtext(f"{ns}lastmod") or "").strip() or None)
            for e in root.findall(f"{ns}url")]
    return [], urls


async def discover_job_urls(session, careers_url: str, max_sitemaps: int = 25) -> list[tuple[str, str | None]]:
    parsed = urlparse(careers_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    queue = []
    robots = await _text(session, root + "/robots.txt", 200_000)
    if robots:
        queue += re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots)
    queue += [root + "/sitemap.xml", root + "/sitemap_index.xml", careers_url.rstrip("/") + "/sitemap.xml"]
    seen, found = set(), []
    while queue and len(seen) < max_sitemaps:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        txt = await _text(session, sm)
        if not txt or "<" not in txt[:200]:
            continue
        children, urls = _parse_sitemap(txt)
        # Prefer child sitemaps that look job-related.
        children.sort(key=lambda u: 0 if re.search(r"job|career|position|opening", u, re.I) else 1)
        queue = children + queue
        found += [(u, lm) for u, lm in urls if _JOBLIKE.search(urlparse(u).path)]
    return found


def _jobposting_from_html(page: str) -> dict | None:
    for block in _LD_RE.findall(page):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for it in items:
            t = it.get("@type") if isinstance(it, dict) else None
            if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                return it
    return None


def _ld_location(jp: dict) -> tuple[str, str | None]:
    locs = jp.get("jobLocation") or []
    locs = locs if isinstance(locs, list) else [locs]
    parts, country = [], None
    for loc in locs:
        addr = (loc or {}).get("address") or {}
        if isinstance(addr, str):
            parts.append(addr)
            continue
        c = addr.get("addressCountry")
        c = c.get("name") if isinstance(c, dict) else c
        country = country or c
        parts.append(", ".join(x for x in [addr.get("addressLocality"), addr.get("addressRegion"), c] if x))
    if str(jp.get("jobLocationType", "")).upper() == "TELECOMMUTE":
        parts.append("Remote")
        req = jp.get("applicantLocationRequirements") or {}
        req = req[0] if isinstance(req, list) and req else req
        if isinstance(req, dict) and req.get("name"):
            parts.append(req["name"])
    return " / ".join(p for p in parts if p), country


async def list_custom(session, entry: str, *, cutoff: datetime, known: set[str], max_pages: int = 150) -> list[Posting]:
    """`entry` is 'https://careers.example.com | Example Co' (name optional)."""
    url, _, name = [x.strip() for x in entry.partition("|")]
    host = urlparse(url).netloc
    company = name or _pretty(host.replace("careers.", "").replace("jobs.", "").split(".")[0])
    urls = await discover_job_urls(session, url)
    fresh = []
    for u, lastmod in urls:
        uid = f"custom:{host}:{u}"
        lm = _iso(lastmod) if lastmod else None
        if lm and lm < cutoff:
            continue
        if not lm and uid in known:
            continue
        fresh.append((u, lm))
    out: list[Posting] = []
    for u, lm in fresh[:max_pages]:
        page = await _text(session, u)
        if not page:
            continue
        jp = _jobposting_from_html(page)
        if not jp:
            continue
        loc, country = _ld_location(jp)
        org = jp.get("hiringOrganization") or {}
        out.append(Posting(
            source="custom", slug=host, company=(org.get("name") if isinstance(org, dict) else None) or company,
            job_id=u, title=clean_text(jp.get("title") or ""), location=loc,
            url=jp.get("url") or u, posted_at=_iso(jp.get("datePosted")) or lm, country=country,
            description=clean_text(jp.get("description") or ""),
        ))
    return out
