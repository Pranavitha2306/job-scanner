"""Daily scan of company career sites for AI/ML roles that match your resume.

Usage:
  python -m jobscan.scanner                    # full run (writes results/, sends alerts)
  python -m jobscan.scanner --dry-run          # full run, no email/Telegram
  python -m jobscan.scanner --limit 200        # only the first 200 companies per source (quick test)
  python -m jobscan.scanner --only core        # only Greenhouse/Lever/Ashby/SmartRecruiters/Workday
  python -m jobscan.scanner --company ashby:openai   # scan one company and print everything

How a job gets into your digest:
  1. Title is clearly AI/ML  -> keep.
     Title is generic engineering ("Software Engineer", "Data Engineer", ...) -> read the job
     description and keep it only if the work is clearly AI/ML.
  2. Posted within `lookback_hours`, in the US / US-remote, not sent to you before.
  3. Full job description read. Dropped ONLY if it explicitly says: no visa sponsorship,
     US citizens / green card holders only, US-person (export control), or security clearance;
     or it asks for more than `max_years_required` years. Jobs that don't mention
     sponsorship at all are kept.
  4. Scored against your resume; >= min_match goes in the digest.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import aiohttp
import yaml

from . import extended, fetchers, llm, matching, notify

ROOT = Path(__file__).resolve().parent.parent
LOCAL_TZ = ZoneInfo("America/Chicago")
CORE = set(fetchers.LISTERS)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
def load_companies(source: str, limit: int | None) -> list[str]:
    path = ROOT / "companies" / f"{source}.txt"
    if not path.exists():
        return []
    items = [ln.strip() for ln in path.read_text().splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    return items[:limit] if limit else items


def _load_json(name: str, default):
    p = ROOT / "state" / name
    return json.loads(p.read_text()) if p.exists() else default


def _save_json(name: str, data) -> None:
    p = ROOT / "state" / name
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(data, indent=0, sort_keys=True))


def format_posted(posted_at: datetime | None, now: datetime) -> str:
    """'Oct 28, 2:14 PM CT (3h ago)'; date only when the site gives no time of day."""
    if not posted_at:
        return "date not listed (new since last scan)"
    local = posted_at.astimezone(LOCAL_TZ)
    hours = max(0, (now - posted_at).total_seconds() / 3600)
    ago = f"{int(hours * 60)}m ago" if hours < 1 else f"{int(hours)}h ago" if hours < 48 else f"{int(hours // 24)}d ago"
    utc = posted_at.astimezone(timezone.utc)
    if utc.hour == 0 and utc.minute == 0 and utc.second == 0:
        return f"{local:%b %d} ({ago})"  # date-only from the site
    return f"{local:%b %d, %I:%M %p} CT ({ago})".replace(" 0", " ")


def load_resume() -> str:
    # In a public repo, keep your resume out of git: put it in the RESUME_TEXT secret instead.
    return os.environ.get("RESUME_TEXT") or (ROOT / "resume.txt").read_text()


# ---------------------------------------------------------------------------
# Main scan
# ---------------------------------------------------------------------------
async def scan(args) -> None:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    resume = load_resume()
    profile = matching.ResumeProfile.from_text(resume, cfg.get("extra_skills"))
    inc = matching.compile_patterns(cfg["title_include"])
    exc = matching.compile_patterns(cfg["title_exclude"])
    generic = matching.compile_patterns(cfg.get("title_generic", []))
    min_ai = cfg.get("generic_title_min_ai_concepts", 4)
    max_generic = cfg.get("max_generic_title_checks", 4000)
    excluded_cos = cfg.get("exclude_companies", [])
    us_places = cfg.get("us_places")
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=cfg.get("lookback_hours", 30))
    seen: dict = _load_json("seen.json", {})
    boards_seen: dict = _load_json("boards.json", {})
    stats = dict(companies=0, postings=0, title_hits=0, fresh_us=0, disqualified=0, generic_checked=0)

    timeout = aiohttp.ClientTimeout(total=cfg.get("request_timeout_seconds", 25))
    conn = aiohttp.TCPConnector(limit=cfg.get("concurrency", 60), ttl_dns_cache=600)
    sem = asyncio.Semaphore(cfg.get("concurrency", 60))
    lib_sem = asyncio.Semaphore(cfg.get("library_concurrency", 20))

    async with aiohttp.ClientSession(timeout=timeout, connector=conn) as session:
        # ---- 1. Which boards to scan ------------------------------------------------
        boards: list[tuple[str, str]] = []
        src_cfg = cfg.get("sources", {})
        if args.company:
            src, slug = args.company.split(":", 1)
            boards = [(src, slug)]
        else:
            enabled = [s for s, on in src_cfg.items() if on]
            if args.only == "core":
                enabled = [s for s in enabled if s in CORE]
            for src in enabled:
                if src == "first_party":
                    boards += [(fp, fp) for fp in cfg.get("first_party", [])]
                else:
                    boards += [(src, c) for c in load_companies(src, args.limit)]
        stats["companies"] = len(boards)
        print(f"Scanning {len(boards):,} company career sites...")
        t0, done = time.time(), 0

        async def list_board(src: str, entry: str) -> tuple[str, str, list[fetchers.Posting]]:
            nonlocal done
            slug = entry
            try:
                if src in CORE:
                    async with sem:
                        posts = await fetchers.LISTERS[src](session, entry)
                    slug = entry.split("|")[0].strip()
                elif src == "custom":
                    async with sem:
                        posts = await extended.list_custom(session, entry, cutoff=cutoff, known=set(seen))
                    slug = entry.split("|")[0].strip()
                else:  # ats_scrapers platform or first-party site
                    slug = entry.rsplit("|", 1)[0] if "|" in entry else entry
                    async with lib_sem:
                        posts = await extended.list_library(src, slug, descriptions=False,
                                                            timeout_s=cfg.get("library_timeout_seconds", 180))
                    if "|" in entry:
                        name = entry.rsplit("|", 1)[1]
                        for p in posts:
                            if not p.company or p.company.lower() == slug.lower():
                                p.company = name
            except Exception as e:  # noqa: BLE001
                posts = []
                if args.company:
                    print(f"  error {src}:{entry}: {e}")
            done += 1
            if done % 2000 == 0:
                print(f"  {done:,}/{len(boards):,} sites ({time.time() - t0:.0f}s)")
            return src, slug, posts

        listed = await asyncio.gather(*(list_board(s, c) for s, c in boards))

        # ---- 2. Cheap filters (title, company, freshness, location) ------------------
        ai_titles: list[fetchers.Posting] = []
        generic_titles: list[fetchers.Posting] = []
        for src, slug, posts in listed:
            board_key = f"{src}:{slug}"
            first_time_board = board_key not in boards_seen
            if posts:
                boards_seen[board_key] = now.isoformat()
            for p in posts:
                stats["postings"] += 1
                if args.company:
                    when = f"{p.posted_at:%Y-%m-%d}" if p.posted_at else "?"
                    print(f"  [{when}] {p.title} | {p.location}")
                is_ai = matching.title_ok(p.title, inc, exc)
                is_generic = not is_ai and matching.title_ok(p.title, generic, exc)
                if not (is_ai or is_generic):
                    continue
                if matching.company_excluded(p.company, excluded_cos) or matching.company_excluded(slug, excluded_cos):
                    continue
                if matching.student_role(p.title, ""):
                    continue  # internships, co-ops, new-grad / early-career programs
                if matching.language_problem(p.title, ""):
                    continue  # "(m/w/d)" and similar: European postings
                if not args.company:
                    if p.uid in seen or ("dup:" + matching.dedupe_key(p.company, p.title)) in seen:
                        continue  # already sent (same job, or same role at another location / sister company)
                    if p.posted_at and p.posted_at < cutoff:
                        continue
                    if not p.posted_at and first_time_board:
                        # Undated jobs on a site we've never scanned: remember them, don't report.
                        seen[p.uid] = now.isoformat()
                        continue
                if not matching.is_us_location(p.location, p.country, us_places):
                    continue
                (ai_titles if is_ai else generic_titles).append(p)
        stats["title_hits"] = len(ai_titles)
        generic_titles = generic_titles[:max_generic]
        stats["generic_checked"] = len(generic_titles)
        print(f"Listed {stats['postings']:,} jobs in {time.time() - t0:.0f}s: {len(ai_titles):,} new US AI/ML titles, "
              f"{len(generic_titles):,} new US engineering titles to check for AI/ML work.")

        # ---- 3. Read job descriptions ------------------------------------------------
        to_describe = ai_titles + generic_titles

        async def describe(p):
            if p.description or p.source not in CORE:
                return
            async with sem:
                try:
                    p.description = await fetchers.fetch_description(session, p)
                except Exception:  # noqa: BLE001
                    p.description = ""
        await asyncio.gather(*(describe(p) for p in to_describe))
        await extended.describe_library([p for p in to_describe if p.source not in CORE and p.source != "custom"])

        # Generic titles survive only if the JD is clearly AI/ML work.
        generic_ai = [p for p in generic_titles if matching.ai_intensity(p.description) >= min_ai]
        candidates = ai_titles + generic_ai
        stats["fresh_us"] = len(candidates)
        print(f"{len(generic_ai):,} of the engineering titles are AI/ML work; {len(candidates):,} candidates total.")

        # ---- 4. Explicit exclusions + keyword score -----------------------------------
        scored = []
        excluded: list[dict] = []  # shown at the bottom of the email so you can double-check the filters
        max_years = cfg.get("max_years_required", 6)
        for p in candidates:
            text = p.description or ""
            if p.country and not matching.is_us_location(p.location, p.country, us_places):
                continue
            if not matching.description_location_ok(p.location, text):
                stats["non_us"] = stats.get("non_us", 0) + 1
                continue  # "Remote" job whose description says it's outside the US
            flags = matching.disqualifiers(text)
            if matching.student_role(p.title, text):
                flags.append("intern / student / new-grad role")
            for check in (matching.language_problem(p.title, text), matching.employment_problem(p.title, text),
                          matching.senior_problem(text)):
                if check:
                    flags.append(check)
            yrs = matching.years_required(text)
            if yrs and yrs > max_years:
                flags.append(f"{yrs}+ years")
            score, got, miss = matching.keyword_match(f"{p.title} {text}", profile)
            if not text:
                score = min(score, 60)  # couldn't read the JD: never claim a strong match
            off = matching.off_domains(f"{p.title} {text}")
            if off:
                # The JD's core work is in a field that isn't on your resume: keyword overlap
                # on "LLM", "Python", "Kafka" etc. would overstate the fit.
                score = max(0, score - 15 * len(off))
                miss = [f"core skill area not on resume: {d}" for d in off] + miss
                if cfg.get("strict_domain", True):
                    flags.append("off-target: " + ", ".join(off))
            row = dict(match=score, company=p.company, title=p.title, location=p.location,
                       posted=format_posted(p.posted_at, now),
                       url=p.url, source=p.source, years=yrs or "", comp=p.extra.get("comp", ""),
                       summary="" if text else "Couldn't read the job description; check it yourself.",
                       gaps=", ".join(miss[:4]), flags="; ".join(flags), _p=p)
            if flags:
                stats["disqualified"] += 1
                excluded.append(row)
                continue
            scored.append(row)

        # ---- 5. Optional LLM re-score -------------------------------------------------
        lcfg = cfg.get("llm", {}) or {}
        if lcfg.get("enabled") and not args.no_llm and os.environ.get("ANTHROPIC_API_KEY"):
            pool = sorted([r for r in scored if r["match"] >= lcfg.get("prefilter_min", 50) and r["_p"].description],
                          key=lambda r: -r["match"])[: lcfg.get("max_jobs_per_run", 60)]
            llm_sem = asyncio.Semaphore(4)

            async def rescore(r):
                async with llm_sem:
                    p = r["_p"]
                    res = await llm.llm_score(session, lcfg.get("model", "claude-haiku-5-5"), resume,
                                              p.title, p.company, p.location, p.description)
                if not res:
                    return
                r["match"] = int(res.get("match_pct", r["match"]))
                r["summary"] = res.get("summary", "")
                if res.get("gaps"):
                    r["gaps"] = ", ".join(res["gaps"][:3])
                if res.get("disqualified"):
                    r["flags"] = res.get("disqualify_reason") or "disqualified"
                if res.get("level_ok") is False:
                    r["flags"] = (r["flags"] + "; level").strip("; ")
                if res.get("years_required"):
                    r["years"] = res["years_required"]
                if res.get("us_based") is False:
                    r["flags"] = (r["flags"] + "; not US-based").strip("; ")
                if res.get("student_role") is True:
                    r["flags"] = (r["flags"] + "; intern/student role").strip("; ")
                if res.get("core_domain_fit") is False:
                    r["flags"] = (r["flags"] + "; off-target role").strip("; ")
                if res.get("english_only") is False:
                    r["flags"] = (r["flags"] + "; needs another language").strip("; ")
                if res.get("full_time_employee") is False:
                    r["flags"] = (r["flags"] + "; freelance / part-time / outsourcing").strip("; ")
            if pool:
                print(f"LLM scoring {len(pool)} jobs...")
                await asyncio.gather(*(rescore(r) for r in pool))
            before = len(scored)
            excluded += [r for r in scored if r["flags"]]
            scored = [r for r in scored if not r["flags"]]
            stats["disqualified"] += before - len(scored)

    # ---- 6. Remove duplicates (same role in several cities / on sister-company sites) -----
    scored.sort(key=lambda r: -r["match"])
    merged: dict[str, dict] = {}
    for r in scored:
        key = matching.dedupe_key(r["company"], r["title"])
        if key not in merged:
            r["_locs"] = [r["location"]] if r["location"] else []
            merged[key] = r
        else:
            keep = merged[key]
            if r["location"] and r["location"] not in keep["_locs"]:
                keep["_locs"].append(r["location"])
            if r["company"] not in keep["company"]:
                keep["company"] = f"{keep['company']} / {r['company']}"
    for r in merged.values():
        locs = r.pop("_locs", [])
        if len(locs) > 1:
            r["location"] = "; ".join(locs[:3]) + (f" (+{len(locs) - 3} more)" if len(locs) > 3 else "")
    stats["duplicates_removed"] = len(scored) - len(merged)
    scored = list(merged.values())

    # ---- 7. Digest ---------------------------------------------------------------------
    scored.sort(key=lambda r: -r["match"])
    strong = [r for r in scored if r["match"] >= cfg.get("min_match", 70)]
    close = [r for r in scored if cfg.get("near_miss_min", 60) <= r["match"] < cfg.get("min_match", 70)]
    day = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
    stats["excluded_list"] = sorted(excluded, key=lambda r: -r["match"])
    md = notify.build_markdown(day, strong, close, stats)
    print("\n" + md)
    if args.company:
        return

    if cfg.get("save_results_in_repo", True):
        notify.write_files(ROOT / "results", day, md, strong + close)
    hours = _load_json("posting_hours.json", {}) if not args.company else {}
    for p in candidates:
        if p.posted_at and p.posted_at.hour + p.posted_at.minute:  # skip date-only stamps (midnight)
            local = p.posted_at.astimezone(LOCAL_TZ)
            key = f"{local:%a} {local:%H}"
            hours[key] = hours.get(key, 0) + 1
    stats["posting_hours"] = hours
    for p in candidates + generic_titles:
        seen[p.uid] = now.isoformat()
    for p in candidates:
        seen["dup:" + matching.dedupe_key(p.company, p.title)] = now.isoformat()
    keep_after = (now - timedelta(days=60)).isoformat()
    _save_json("seen.json", {k: v for k, v in seen.items() if v >= keep_after})
    _save_json("boards.json", boards_seen)
    _save_json("posting_hours.json", hours)
    if not args.dry_run and (strong or close or args.always_send):
        subject = f"{len(strong)} AI/ML job matches today" + (f" (+{len(close)} close)" if close else "")
        sent = notify.send_email(subject, notify.build_html(strong, close, day, stats), md)
        sent_tg = notify.send_telegram(md)
        print(f"Email sent: {sent}; Telegram sent: {sent_tg}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="don't send email/Telegram")
    ap.add_argument("--limit", type=int, default=None, help="only N companies per source")
    ap.add_argument("--only", choices=["core", "all"], default="all", help="core = the 5 main platforms only")
    ap.add_argument("--company", help="scan one site, e.g. ashby:openai, greenhouse:stripe, icims:<slug>")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--always-send", action="store_true", help="send even when there are no matches")
    asyncio.run(scan(ap.parse_args()))


if __name__ == "__main__":
    main()
