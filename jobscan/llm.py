"""Optional LLM scoring: compares the full job description with your resume.

Enabled when the ANTHROPIC_API_KEY environment variable is set and `llm.enabled` is true.
Returns None on any failure so the scanner falls back to keyword scores.
"""
from __future__ import annotations

import json
import os
import re

import aiohttp

PROMPT = """You screen job postings for one candidate. Compare the JOB DESCRIPTION with the RESUME.

Return ONLY a JSON object with these keys:
- "match_pct": integer 0-100, how well the resume meets the job's stated requirements (be realistic, not generous; a perfect stack match with missing required years should still lose points)
- "disqualified": true if the posting requires US citizenship, a green card, security clearance, US-person status, or says it will not sponsor visas; otherwise false
- "disqualify_reason": short string or ""
- "level_ok": false if the role is clearly staff/principal/lead/manager or needs more than 6 years; otherwise true
- "years_required": integer or null
- "top_matches": up to 3 short strings, the strongest overlaps
- "gaps": up to 3 short strings, the most important missing requirements
- "summary": one sentence on fit

RESUME:
{resume}

JOB: {title} at {company} ({location})
JOB DESCRIPTION:
{jd}
"""


async def llm_score(session: aiohttp.ClientSession, model: str, resume: str, title: str,
                    company: str, location: str, jd: str) -> dict | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    body = {
        "model": model,
        "max_tokens": 600,
        "messages": [{"role": "user", "content": PROMPT.format(
            resume=resume[:9000], title=title, company=company, location=location, jd=jd[:14000])}],
    }
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    try:
        async with session.post("https://api.anthropic.com/v1/messages", json=body, headers=headers,
                                timeout=aiohttp.ClientTimeout(total=90)) as r:
            if r.status != 200:
                print(f"  LLM error {r.status}: {(await r.text())[:200]}")
                return None
            data = await r.json()
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        m = re.search(r"\{.*\}", text, re.DOTALL)
        return json.loads(m.group(0)) if m else None
    except Exception as e:  # noqa: BLE001 - never let scoring crash the run
        print(f"  LLM exception: {e}")
        return None
