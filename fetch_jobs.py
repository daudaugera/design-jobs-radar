#!/usr/bin/env python3
"""Fetch design vacancies from several feeds, filter them, and update:
   docs/data/jobs.json  (what the website shows)
   data/digest.json     (what the morning notification sends)

Run:  python scripts/fetch_jobs.py            (live)
      python scripts/fetch_jobs.py --selftest (offline logic test, no network)
"""
import argparse
import csv
import datetime as dt
import html
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEADERS = {"User-Agent": "design-jobs-radar/1.0 (personal job-alert tool)"}
TIMEOUT = 30

COUNTRY_NAMES = {
    "gb": "United Kingdom", "de": "Germany", "nl": "Netherlands", "fr": "France", "es": "Spain",
    "it": "Italy", "at": "Austria", "be": "Belgium", "ch": "Switzerland", "pl": "Poland",
}

ACCEPT_LOC = re.compile(r"\b(europe|european|eu|emea|worldwide|anywhere|global|world|malta|cet)\b", re.I)
REJECT_LOC = re.compile(
    r"\b(us|usa|u\.s\.|united states|canada|north america|americas|latam|latin america|apac|asia|"
    r"australia|new zealand|india|brazil|mexico)\b", re.I)

VISA_POS = [
    r"visa\s*sponsor", r"sponsor(?:ship)?\s+(?:a\s+|your\s+|the\s+)?(?:work\s+|skilled\s+worker\s+)?(?:visa|permit)",
    r"\b(?:we|can|will|able to|happy to|willing to)\s+sponsor", r"skilled worker", r"blue card",
    r"certificate of sponsorship", r"visa support", r"work permit (?:support|sponsorship|assistance)",
]
RELOC_POS = [
    r"relocation\s+(?:support|assistance|package|bonus|budget|allowance|help|benefit)",
    r"we (?:can |will )?relocate", r"relocate you", r"help(?:ing)? you relocate",
]
NEG = [
    r"no\s+(?:visa\s+)?sponsorship",
    r"(?:unable|not able|cannot|can't|can not|won't|will not|do not|don't|does not|doesn't)\s+(?:to\s+)?(?:offer\s+|provide\s+)?(?:visa\s+)?sponsor",
    r"sponsorship\s+(?:is\s+)?(?:not|unavailable)",
    r"without\s+(?:the need for\s+)?sponsorship",
]


# ----------------------------------------------------------------- helpers
def log(*a):
    print(*a, file=sys.stderr)


def clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def to_date(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return dt.datetime.fromtimestamp(v, dt.timezone.utc).date().isoformat()
    m = re.search(r"\d{4}-\d{2}-\d{2}", str(v))
    return m.group(0) if m else None


def norm_company(name):
    n = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    n = re.sub(r"\b(ltd|limited|plc|llp|llc|inc|uk|group|the|gmbh|bv|ag)\b", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def load_sponsors():
    p = ROOT / "data" / "sponsors.csv"
    if not p.exists():
        return set()
    out = set()
    with p.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if row:
                out.add(norm_company(row[0]))
    out.discard("")
    out.discard("organisation name")
    return out


def any_match(patterns, text):
    return any(re.search(p, text, re.I) for p in patterns)


def remote_scope(location):
    loc = location or ""
    if ACCEPT_LOC.search(loc):
        return "yes"
    if REJECT_LOC.search(loc):
        return "no"
    return "maybe"


def job(source, jid, title, company, location, url, posted, remote, description, country, visa_flag=False, tags=None):
    return {"id": f"{source}:{jid}", "source": source, "title": clean(title), "company": clean(company),
            "location": clean(location), "url": url, "posted": to_date(posted), "remote": bool(remote),
            "description": clean(description), "country": country, "visa_flag": visa_flag, "tags": tags or []}


# ----------------------------------------------------------------- sources
def _get(url, **params):
    import requests
    r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def fetch_arbeitnow(base, country, pages, visa):
    out = []
    for page in range(1, pages + 1):
        params = {"page": page}
        if visa:
            params["visa_sponsorship"] = "true"
        data = _get(f"{base}/api/job-board-api", **params).get("data") or []
        if not data:
            break
        for j in data:
            out.append(job("arbeitnow", j.get("slug") or j.get("url"), j.get("title"), j.get("company_name"),
                           j.get("location"), j.get("url"), j.get("created_at"), j.get("remote"),
                           j.get("description"), country, visa_flag=visa, tags=j.get("tags") or []))
    return out


def fetch_jobicy():
    out = []
    for geo in ("europe", "anywhere", "uk"):
        data = _get("https://jobicy.com/api/v2/remote-jobs", count=100, geo=geo).get("jobs") or []
        for j in data:
            loc = j.get("jobGeo")
            loc = ", ".join(loc) if isinstance(loc, list) else loc
            out.append(job("jobicy", j.get("id"), j.get("jobTitle"), j.get("companyName"), loc, j.get("url"),
                           j.get("pubDate"), True, j.get("jobDescription") or j.get("jobExcerpt"), "Remote"))
    return out


def fetch_remotive():
    out = []
    data = _get("https://remotive.com/api/remote-jobs", category="design").get("jobs") or []
    for j in data:
        out.append(job("remotive", j.get("id"), j.get("title"), j.get("company_name"),
                       j.get("candidate_required_location"), j.get("url"), j.get("publication_date"), True,
                       j.get("description"), "Remote", tags=j.get("tags") or []))
    return out


def fetch_adzuna(cfg):
    app_id, app_key = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        return None
    out = []
    for cc in cfg["adzuna_countries"]:
        for q in cfg["adzuna_queries"]:
            try:
                data = _get(f"https://api.adzuna.com/v1/api/jobs/{cc}/search/1", app_id=app_id, app_key=app_key,
                            results_per_page=50, what=q, max_days_old=3)
            except Exception as e:  # one bad country/query must not stop the rest
                log(f"adzuna {cc} '{q}': {e}")
                continue
            for j in data.get("results") or []:
                out.append(job("adzuna", j.get("id"), j.get("title"), (j.get("company") or {}).get("display_name"),
                               (j.get("location") or {}).get("display_name"), j.get("redirect_url"),
                               j.get("created"), False, j.get("description"), COUNTRY_NAMES.get(cc, cc.upper())))
    return out


# ----------------------------------------------------------------- filtering
def process(raw, cfg, existing, sponsors, today):
    inc = [re.compile(p, re.I) for p in cfg["title_include"]]
    exc = [re.compile(p, re.I) for p in cfg["title_exclude"]]
    jobs = {j["id"]: j for j in existing}
    new_ids = []
    for r in raw:
        title = r["title"]
        if not r.get("url") or not any(p.search(title) for p in inc) or any(p.search(title) for p in exc):
            continue
        text = f"{title} {r['description']}"
        neg = any_match(NEG, text)
        sponsor = (r["visa_flag"] or any_match(VISA_POS, text)) and not neg
        reloc = any_match(RELOC_POS, text)
        register = bool(sponsors) and norm_company(r["company"]) in sponsors
        remote = r["remote"] or bool(re.search(r"\bremote\b|work from home|fully distributed", f"{title} {r['location']}", re.I))
        scope = remote_scope(r["location"]) if remote else None
        if not (sponsor or reloc or register or scope in ("yes", "maybe")):
            continue
        rec = {
            "id": r["id"], "title": title, "company": r["company"], "location": r["location"], "url": r["url"],
            "source": r["source"], "country": r["country"], "posted": r["posted"], "remote": remote,
            "remote_scope": scope, "sponsor": bool(sponsor), "relocation": bool(reloc),
            "no_sponsorship": neg, "uk_register": register, "summary": r["description"][:280],
            "tags": r["tags"][:6],
        }
        if rec["id"] in jobs:
            old = jobs[rec["id"]]
            rec["first_seen"] = old.get("first_seen", today)
        else:
            rec["first_seen"] = today
            new_ids.append(rec["id"])
        rec["last_seen"] = today
        jobs[rec["id"]] = rec

    d = dt.date.fromisoformat(today)
    keep = []
    for j in jobs.values():
        age = (d - dt.date.fromisoformat(j["first_seen"])).days
        unseen = (d - dt.date.fromisoformat(j.get("last_seen", j["first_seen"]))).days
        if age <= cfg["keep_days"] and unseen <= cfg["drop_if_unseen_days"]:
            keep.append(j)
    keep.sort(key=lambda j: (j["first_seen"], j.get("posted") or ""), reverse=True)
    kept_ids = {j["id"] for j in keep}
    return keep, [i for i in new_ids if i in kept_ids]


# ----------------------------------------------------------------- main
def run_live(cfg, today):
    sources = {
        "Arbeitnow DE (visa-flagged)": lambda: fetch_arbeitnow("https://www.arbeitnow.com", "Europe (DACH)", cfg["arbeitnow_visa_pages"], True),
        "Arbeitnow DE (general)": lambda: fetch_arbeitnow("https://www.arbeitnow.com", "Europe (DACH)", cfg["arbeitnow_general_pages"], False),
        "Arbeitnow UK (visa-flagged)": lambda: fetch_arbeitnow("https://www.arbeitnow.co.uk", "United Kingdom", cfg["arbeitnow_visa_pages"], True),
        "Arbeitnow UK (general)": lambda: fetch_arbeitnow("https://www.arbeitnow.co.uk", "United Kingdom", cfg["arbeitnow_general_pages"], False),
        "Jobicy": fetch_jobicy,
        "Remotive": fetch_remotive,
        "Adzuna": lambda: fetch_adzuna(cfg),
    }
    raw, status = [], {}
    for name, fn in sources.items():
        try:
            res = fn()
            if res is None:
                status[name] = "not configured"
                continue
            raw += res
            status[name] = f"{len(res)} fetched"
        except Exception as e:
            status[name] = f"failed: {type(e).__name__}"
            log(f"{name}: {e}")
    return raw, status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    cfg = json.loads((ROOT / "config.json").read_text())
    if args.selftest:
        return selftest(cfg)

    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    jobs_path = ROOT / "docs" / "data" / "jobs.json"
    existing = json.loads(jobs_path.read_text())["jobs"] if jobs_path.exists() else []
    raw, status = run_live(cfg, today)
    if raw:
        jobs, new_ids = process(raw, cfg, existing, load_sponsors(), today)
    else:  # every source failed: keep yesterday's data rather than wiping the site
        log("No data fetched from any source; keeping existing jobs.")
        jobs, new_ids = existing, []
    meta = {"updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "today": today,
            "sources": status, "links": cfg["search_links"], "register_loaded": bool(load_sponsors())}
    jobs_path.parent.mkdir(parents=True, exist_ok=True)
    jobs_path.write_text(json.dumps({"meta": meta, "jobs": jobs}, indent=1, ensure_ascii=False))
    by_id = {j["id"]: j for j in jobs}
    digest = {"date": today, "new": [by_id[i] for i in new_ids], "total": len(jobs), "sources": status}
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "digest.json").write_text(json.dumps(digest, indent=1, ensure_ascii=False))
    print(f"{len(jobs)} jobs on site, {len(new_ids)} new today. Sources: {status}")


# ----------------------------------------------------------------- offline test
def selftest(cfg):
    def mk(title, company="Acme", loc="", desc="", remote=False, country="United Kingdom", visa=False, url="https://x.test/1", i=[0]):
        i[0] += 1
        return job("test", i[0], title, company, loc, url, "2026-11-24", remote, desc, country, visa_flag=visa)

    raw = [
        mk("Senior Brand Designer", desc="We offer visa sponsorship for the right candidate."),             # keep (sponsor)
        mk("Graphic Designer", desc="Great team. Right to work in UK required. We do not sponsor visas."),    # drop (neg, no other signal)
        mk("Graphic Designer", desc="Hybrid role. Relocation package available.", loc="Berlin"),              # keep (reloc)
        mk("UX Designer", desc="visa sponsorship available"),                                                   # drop (excluded title)
        mk("Visual Designer", loc="Worldwide", remote=True, country="Remote"),                                  # keep (remote yes)
        mk("Visual Designer", loc="USA only", remote=True, country="Remote"),                                   # drop (remote no)
        mk("Art Director", company="Wagamama Limited", desc="Great brand."),                                    # keep only with register
        mk("Brand Designer", desc="Plain London studio job.", loc="London"),                                    # drop (no signal)
        mk("Creative Director", loc="Munich", visa=True, country="Europe (DACH)"),                              # keep (visa flag)
        mk("Software Engineer", desc="visa sponsorship"),                                                       # drop (title)
        mk("Brand Designer", desc="x", url=""),                                                                 # drop (no url)
    ]
    jobs, new = process(raw, cfg, [], set(), "2026-11-25")
    titles = sorted(j["title"] for j in jobs)
    assert titles == ["Creative Director", "Graphic Designer", "Senior Brand Designer", "Visual Designer"], titles
    jobs_r, _ = process(raw, cfg, [], {norm_company("Wagamama Limited")}, "2026-11-25")
    assert any(j["title"] == "Art Director" and j["uk_register"] for j in jobs_r)
    # second run: same data -> nothing new; first_seen preserved
    jobs2, new2 = process(raw, cfg, jobs, set(), "2026-11-26")
    assert new2 == [] and all(j["first_seen"] == "2026-11-25" for j in jobs2)
    # expiry: a job unseen for >7 days is dropped
    jobs3, _ = process([], cfg, jobs, set(), "2026-12-10")
    assert jobs3 == [], jobs3
    assert norm_company("Wagamama Limited") == norm_company("WAGAMAMA LTD")
    print("selftest OK:", len(jobs), "kept of", len(raw))


if __name__ == "__main__":
    main()
