#!/usr/bin/env python3
"""Send the morning digest by email and/or Telegram.

Email  : set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, EMAIL_TO (secrets in GitHub).
Telegram: set TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.
If neither is set, the digest is just printed (nothing is sent).
"""
import html
import json
import os
import smtplib
import ssl
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def badges(j):
    b = []
    if j.get("sponsor"):
        b.append("Visa sponsorship")
    if j.get("relocation"):
        b.append("Relocation")
    if j.get("uk_register"):
        b.append("UK licensed sponsor")
    if j.get("remote"):
        scope = {"yes": "Remote (Europe/worldwide)", "maybe": "Remote (check location rules)"}.get(j.get("remote_scope"), "Remote")
        b.append(scope)
    return b


def build(digest, cfg, site_url):
    jobs = digest["new"]
    n = len(jobs)
    shown = jobs[: cfg["max_in_email"]]
    subject = f"Design jobs: {n} new today" if n else "Design jobs: no new matches today"
    text = [f"{n} new matching vacancies today ({digest['total']} currently on the site).", ""]
    rows = []
    for j in shown:
        meta = " | ".join(x for x in (j["company"], j["location"], j["country"]) if x)
        tag = ", ".join(badges(j))
        text += [f"- {j['title']} - {meta}", f"  {tag}" if tag else "", f"  {j['url']}", ""]
        rows.append(
            f"<p style='margin:0 0 14px'><a href='{html.escape(j['url'])}' style='font-weight:700;color:#111'>"
            f"{html.escape(j['title'])}</a><br><span style='color:#555'>{html.escape(meta)}</span><br>"
            f"<span style='color:#b3300f;font-size:12px'>{html.escape(tag)}</span></p>")
    if n > len(shown):
        text.append(f"...and {n - len(shown)} more on the site.")
    if site_url:
        text.append(f"Full list and filters: {site_url}")
    failed = [k for k, v in digest.get("sources", {}).items() if str(v).startswith("failed")]
    if failed:
        text.append("Sources that failed today: " + ", ".join(failed))
    body = (f"<div style='font-family:Arial,sans-serif;max-width:620px'><h2 style='margin:0 0 6px'>{html.escape(subject)}</h2>"
            f"<p style='color:#555'>{digest['total']} matching vacancies are currently on the site.</p>{''.join(rows)}"
            + (f"<p><a href='{html.escape(site_url)}'>Open the full list with filters</a></p>" if site_url else "")
            + (f"<p style='color:#a05a00'>Sources that failed today: {html.escape(', '.join(failed))}</p>" if failed else "")
            + "</div>")
    return subject, "\n".join(text), body


def send_email(subject, text, body):
    host, user, pw, to = (os.getenv(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "EMAIL_TO"))
    if not all((host, user, pw, to)):
        return False
    port = int(os.getenv("SMTP_PORT") or 465)
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(body, "html", "utf-8"))
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
            s.login(user, pw)
            s.sendmail(user, [a.strip() for a in to.split(",")], msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(user, pw)
            s.sendmail(user, [a.strip() for a in to.split(",")], msg.as_string())
    return True


def send_telegram(text):
    import requests
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return False
    for i in range(0, len(text), 3800):
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": text[i:i + 3800], "disable_web_page_preview": True}, timeout=30)
        r.raise_for_status()
    return True


def main():
    force = "--force" in sys.argv
    cfg = json.loads((ROOT / "config.json").read_text())
    digest = json.loads((ROOT / "data" / "digest.json").read_text())
    state_path = ROOT / "data" / "notify_state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    if state.get("last_notified") == digest["date"] and not force:
        print("Already notified today; skipping (use --force to resend).")
        return
    if not digest["new"] and not cfg["send_when_empty"]:
        print("No new jobs today; nothing to send.")
        return
    subject, text, body = build(digest, cfg, os.getenv("SITE_URL", ""))
    sent = []
    if send_email(subject, text, body):
        sent.append("email")
    if send_telegram(subject + "\n\n" + text):
        sent.append("telegram")
    if not sent:
        print("No notification channel configured. Digest preview:\n\n" + text)
        return
    state_path.write_text(json.dumps({"last_notified": digest["date"], "via": sent}))
    print("Notified via", ", ".join(sent))


if __name__ == "__main__":
    main()
