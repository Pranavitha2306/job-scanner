# AI/ML Job Scanner

Every morning it checks **about 59,000 company career sites**, reads the job descriptions, and emails you the new US AI/ML engineering roles that match your resume, with direct apply links. It runs free on GitHub Actions, so your computer can be off.

## What it checks

| Where | Sites | Examples |
|---|---|---|
| Greenhouse, Lever, Ashby, SmartRecruiters, Workday | ~28,300 | Stripe, Databricks, OpenAI, Ramp, NVIDIA, Salesforce, Capital One |
| Careers systems behind companies' **own-branded** careers sites: iCIMS, Taleo, SuccessFactors, Oracle, Phenom, Eightfold, Avature, BambooHR, Workable, Paycom, JazzHR, Rippling, Breezy, Recruitee, Cornerstone, Gem, Pinpoint, Dayforce, ADP, Recruiterbox, UKG, Paylocity, Jobvite | ~31,000 | Microsoft (Eightfold), GE HealthCare (Phenom), ABB |
| Big companies with their own systems | 5 | Google, Apple, Uber, TikTok, ByteDance |
| **Any other careers site you add** to `companies/custom.txt` | your list | read via the site's sitemap and the job's structured data |

Most company careers pages that look custom ("careers.bigcompany.com") actually run on one of the systems above. For the rest, add the URL to `companies/custom.txt`.

## How a job gets into your email

1. **Title.** AI/ML titles (AI Engineer, ML Engineer, Applied AI, GenAI, LLM, Forward Deployed...) are kept. Generic engineering titles ("Software Engineer", "Data Engineer", "Developer") are kept **only if the job description shows AI/ML work**: at least 4 of LLMs, RAG, agents, LangChain/LangGraph, vector DBs, evals, PyTorch, MLOps and so on. Senior, Staff, Principal, Lead, Manager, Intern and Research Scientist titles are skipped (edit the list in `config.yaml`).
2. **New and in the US.** It must be posted in the last 30 hours, in the US or US-remote, and not already sent to you.
3. **Job description read.** A job is dropped **only if the description explicitly says**:
   - no visa sponsorship, or
   - US citizens or green card holders only, US-person (export control), or a security clearance, or
   - more than 6 years of experience.

   **Jobs that don't mention sponsorship at all are kept.**
4. **Scored against your resume.** It uses keyword overlap. If you add an Anthropic API key, an LLM reads the description instead and gives a realistic match %, a one-line summary and the top gaps.
5. **Emailed.** Matches of **70%+** come first, followed by "close" matches (60–69%).

## Setup (about 15 minutes)

### 1. Create a GitHub repo
**Recommended: a public repo with your resume kept as a secret.** Public repos get unlimited free Actions minutes, and a full scan of every source can take about an hour.
- Upload everything in this folder, including the hidden `.github` folder, **except `resume.txt`**.
- In `config.yaml`, set `save_results_in_repo: false`.

*Or use a private repo:* upload everything including `resume.txt`. Private repos get 2,000 free minutes a month, which may run out with daily full scans. If it does, switch to core-only runs (step 4).

### 2. Add secrets
Go to **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret | Value |
|---|---|
| `RESUME_TEXT` | your resume as plain text (required for a public repo) |
| `SMTP_USER` | your Gmail address |
| `SMTP_PASSWORD` | a Gmail **App Password** (Google Account → Security → 2-Step Verification → App passwords). Your normal password won't work. |
| `EMAIL_TO` | where to send the digest |
| `ANTHROPIC_API_KEY` | *(recommended)* from console.anthropic.com, for realistic match % and gaps |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | *(optional)* Telegram alerts as well as email |

### 3. Test it
Go to **Actions → Daily AI/ML job scan → Run workflow**. Enter `100` in **limit** for a quick test, then run it again with limit empty for a full scan.

### 4. Schedule
- **6:37 AM Central:** full scan of every source.
- **4:37 PM Central:** quick re-scan of the 5 core platforms.

To save minutes, delete the afternoon `cron` line in `.github/workflows/daily-scan.yml`. To make the morning run core-only as well, set the sources you don't want to `false` in `config.yaml`.

## Customizing

- **Main settings in `config.yaml`:** `min_match`, `lookback_hours`, `max_years_required`, title lists, `generic_title_min_ai_concepts`, excluded companies, and which sources are on.
- **Add companies:** add a line to the right file in `companies/`. Examples: `greenhouse.txt` takes `stripe`, `ashby.txt` takes `openai`, `workday.txt` takes `tenant|wdN|site|Name`, and `custom.txt` takes `https://careers.example.com | Example`.
- **Check one site by hand:** run `python -m jobscan.scanner --company greenhouse:stripe`, or `--company icims:<slug>`, or `--company custom:"https://careers.example.com | Example"`.

## Limits, honestly

- **No repeats:** jobs it has sent or checked are remembered in `state/seen.json`.
- **Undated jobs:** Google, for example, doesn't publish dates. The first time a site is scanned, its existing undated jobs are recorded and not sent. After that, any new ones are sent.
- **Custom sites:** sites that load jobs only with JavaScript and publish no sitemap can't be read. Use LinkedIn alerts for those.
- **Not covered:** Meta and Tesla need a full browser to scrape and aren't included.
- **Some sites will fail:** a few will have changed or be dead on any given day, and those are skipped quietly.
- **Sponsorship detection is text-based:** it catches clear statements like "unable to sponsor" or "must be a U.S. citizen." Confirm anything unclear with the recruiter.

Company lists come from the open datasets [pa-nuzz/company-dataset-](https://github.com/pa-nuzz/company-dataset-), [kalil0321/ats-scrapers](https://github.com/kalil0321/ats-scrapers) (MIT, also used for the extra careers systems) and [Feashliaa/job-board-aggregator](https://github.com/Feashliaa/job-board-aggregator).
