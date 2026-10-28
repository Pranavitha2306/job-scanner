"""Write the daily digest to files and send it by email and/or Telegram."""
from __future__ import annotations

import csv
import html
import os
import smtplib
import ssl
import urllib.parse
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


def _line(r: dict) -> str:
    posted = r["posted"] or "?"
    bits = [f"**{r['match']}%**", f"{r['company']} - {r['title']}", r["location"] or "", f"posted {posted}"]
    if r.get("comp"):
        bits.append(r["comp"])
    s = " | ".join(b for b in bits if b)
    s += f"\n  Apply: {r['url']}"
    if r.get("summary"):
        s += f"\n  {r['summary']}"
    if r.get("gaps"):
        s += f"\n  Gaps: {r['gaps']}"
    if r.get("years"):
        s += f"  (asks {r['years']}+ yrs)"
    return s


def build_markdown(day: str, strong: list[dict], close: list[dict], stats: dict) -> str:
    out = [f"# AI/ML job matches - {day}", ""]
    out.append(f"Scanned {stats['companies']:,} company career sites ({stats['postings']:,} open jobs). "
               f"New US jobs checked: {stats['title_hits']:,} AI/ML titles + {stats.get('generic_checked', 0):,} "
               f"engineering titles read for AI/ML work -> {stats['fresh_us']:,} candidates; "
               f"{stats['disqualified']:,} excluded because the description explicitly rules you out "
               f"(no sponsorship, citizens/green card only, clearance, intern/student, or too many years); "
               f"{stats.get('non_us', 0):,} remote jobs dropped as outside the US; "
               f"{stats.get('duplicates_removed', 0):,} duplicate postings merged.")
    out.append("")
    out.append(f"## Strong matches ({len(strong)})")
    out += [f"- {_line(r)}" for r in strong] or ["- None today."]
    if close:
        out += ["", f"## Close matches ({len(close)})"]
        out += [f"- {_line(r)}" for r in close]
    return "\n".join(out) + "\n"


def build_html(md_strong: list[dict], md_close: list[dict], day: str, stats: dict) -> str:
    def rows(items):
        h = []
        for r in items:
            extra = " &middot; ".join(html.escape(x) for x in [r.get("location", ""), f"posted {r['posted']}", r.get("comp", "")] if x)
            h.append(
                f"<li style='margin-bottom:10px'><b>{r['match']}%</b> &nbsp;"
                f"<a href='{html.escape(r['url'])}'>{html.escape(r['company'])} &ndash; {html.escape(r['title'])}</a>"
                f"<br><span style='color:#555'>{extra}</span>"
                + (f"<br>{html.escape(r['summary'])}" if r.get("summary") else "")
                + (f"<br><span style='color:#a33'>Gaps: {html.escape(r['gaps'])}</span>" if r.get("gaps") else "")
                + "</li>")
        return "".join(h) or "<li>None today.</li>"
    return (f"<h2>AI/ML job matches &ndash; {day}</h2>"
            f"<p>Scanned {stats['companies']:,} career sites &middot; {stats['fresh_us']:,} new US AI/ML postings "
            f"&middot; {stats['disqualified']:,} excluded.</p>"
            f"<h3>Strong matches ({len(md_strong)})</h3><ul>{rows(md_strong)}</ul>"
            + (f"<h3>Close matches ({len(md_close)})</h3><ul>{rows(md_close)}</ul>" if md_close else ""))


def write_files(out_dir: Path, day: str, markdown: str, rows: list[dict]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{day}.md").write_text(markdown)
    (out_dir / "latest.md").write_text(markdown)
    with open(out_dir / f"{day}.csv", "w", newline="") as f:
        cols = ["match", "company", "title", "location", "posted", "url", "source", "years", "comp", "summary", "gaps", "flags"]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def send_email(subject: str, html_body: str, text_body: str) -> bool:
    user, pwd, to = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASSWORD"), os.environ.get("EMAIL_TO")
    if not (user and pwd and to):
        return False
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context()) as s:
        s.login(user, pwd)
        s.sendmail(user, [a.strip() for a in to.split(",")], msg.as_string())
    return True


def send_telegram(text: str) -> bool:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return False
    chunks, cur = [], ""
    for line in text.replace("**", "").splitlines(keepends=True):
        if len(cur) + len(line) > 3800:
            chunks.append(cur)
            cur = ""
        cur += line
    chunks.append(cur)
    for c in chunks:
        data = urllib.parse.urlencode({"chat_id": chat, "text": c, "disable_web_page_preview": "true"}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=30).read()
    return True
