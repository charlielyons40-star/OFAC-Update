#!/usr/bin/env python3
"""
OFAC Action Tracker - scraper
Fetches latest actions from OFAC and rewrites index.html.
"""

import json, re, time, sys
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OFAC-Tracker/2.0)"}

def fetch(url):
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=15) as r:
            return r.read().decode("utf-8", errors="replace")
    except URLError as e:
        print(f"  WARN: {url}: {e}", file=sys.stderr)
        return ""

PROGRAM_KEYWORDS = {
    "russia":    ["russia","ukraine","eo 14024","eo14024","russian","gl 134","gl134","magnitsky","belarus","glomag"],
    "iran":      ["iran","iranian","ifsr","irgc","itsr","hormuz","gl u"],
    "venezuela": ["venezuela","venezuelan","pdvsa","gl 52","gl 5v","gl 51","gl 54","gl 55","minerals"],
    "cuba":      ["cuba","cuban","cacr"],
    "ct":        ["hizballah","hezbollah","hamas","sdgt","terrorist","terrorism","al-qaeda","isis","isil"],
    "nk":        ["north korea","dprk","npwmd","kwangson","korean"],
    "cyber":     ["cyber","ransomware","darkside","evil corp"],
}

TYPE_KEYWORDS = {
    "designation": ["designated","designation","added to the sdn","sanctioned","blocked persons list"],
    "removal":     ["removed","removal","delisted","unblocked","delisting","deletions"],
    "license":     ["general license","gl ","authorized","authorization","issuance"],
    "update":      ["updated","update","amended","amendment","modified"],
}

def classify(text):
    low = text.lower()
    types = [k for k, kws in TYPE_KEYWORDS.items() if any(w in low for w in kws)]
    programs = [k for k, kws in PROGRAM_KEYWORDS.items() if any(w in low for w in kws)]
    if not types:
        types = ["update"]
    return types, programs

def scrape_ofac():
    print("Fetching OFAC recent actions...")
    html = fetch("https://ofac.treasury.gov/recent-actions")
    if not html:
        return []

    actions = []
    # Find action links and titles
    pattern = re.compile(
        r'<a href="(/recent-actions/(\d{8}[^"]*))">([^<]+)</a>\s*\n\s*\n([^\n]+)\n\s*([^\n<]+)',
        re.MULTILINE
    )
    date_pattern = re.compile(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(\d{4})')

    # Simpler extraction: find all result rows
    rows = re.findall(
        r'<a href="(/recent-actions/(\d{8}[^"]*))">([^<]{10,})</a>.*?(\w+ \d{1,2}, \d{4})',
        html, re.DOTALL
    )

    seen = set()
    for href, slug, title, date_str in rows:
        title = title.strip()
        if title in seen or len(title) < 10:
            continue
        seen.add(title)

        try:
            dt = datetime.strptime(date_str.strip(), "%B %d, %Y").replace(tzinfo=timezone.utc)
        except ValueError:
            dt = datetime.now(timezone.utc)

        types, programs = classify(title)
        actions.append({
            "title": title,
            "desc": title,
            "date_raw": dt,
            "types": types,
            "programs": programs,
            "url": "https://ofac.treasury.gov" + href,
        })

    print(f"  Found {len(actions)} actions from OFAC")
    return actions

def scrape_federal_register():
    print("Fetching Federal Register...")
    url = (
        "https://www.federalregister.gov/api/v1/documents.json"
        "?conditions[agencies][]=office-of-foreign-assets-control"
        "&conditions[type][]=Notice"
        "&order=newest&per_page=15"
        "&fields[]=title&fields[]=publication_date&fields[]=html_url&fields[]=abstract"
    )
    raw = fetch(url)
    if not raw:
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []

    actions = []
    for doc in data.get("results", []):
        title = doc.get("title", "").strip()
        abstract = doc.get("abstract") or ""
        pub_date = doc.get("publication_date", "")
        html_url = doc.get("html_url", "https://www.federalregister.gov")

        if not title or len(title) < 10:
            continue

        try:
            dt = datetime.strptime(pub_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            dt = datetime.now(timezone.utc)

        full_text = title + " " + abstract
        types, programs = classify(full_text)

        actions.append({
            "title": title,
            "desc": abstract if len(abstract) > 20 else title,
            "date_raw": dt,
            "types": types,
            "programs": programs,
            "url": html_url,
        })

    print(f"  Found {len(actions)} actions from Federal Register")
    return actions

def merge(sources):
    seen = set()
    merged = []
    for item in sources:
        key = re.sub(r'\W+', ' ', item["title"].lower()).strip()[:60]
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    merged.sort(key=lambda x: x["date_raw"], reverse=True)
    return merged[:30]

def fmt_date(dt):
    return dt.strftime("%b %-d, %Y")

def ts_int(dt):
    return int(dt.strftime("%Y%m%d"))

def build_js_actions(raw):
    out = []
    for i, item in enumerate(raw, 1):
        dt = item["date_raw"]
        title = item["title"].replace('"', '&quot;').replace("'", "&#39;")
        desc = item["desc"].replace('"', '&quot;').replace("'", "&#39;")
        types_js = json.dumps(item["types"])
        programs_js = json.dumps(item["programs"])
        url = item["url"]
        implications = suggest_implications(item)
        impl_js = json.dumps(implications)

        out.append(
            f'  {{ id:{i}, date:"{fmt_date(dt)}", ts:{ts_int(dt)}, '
            f'title:"{title}", desc:"{desc}", '
            f'types:{types_js}, programs:{programs_js}, '
            f'implications:{impl_js}, url:"{url}" }}'
        )
    return "const ACTIONS = [\n" + ",\n".join(out) + "\n];"

def suggest_implications(item):
    implications = []
    low = item["title"].lower() + " " + item["desc"].lower()

    if "general license" in low or "gl " in low:
        implications.append("Review authorization scope carefully before transacting")
        implications.append("Check expiration dates and conditions in the full GL text")
        implications.append("Coordinate with counsel on interaction with other applicable GLs")
    if "designat" in low:
        implications.append("Screen immediately against updated SDN list")
        implications.append("Block any assets or transactions involving designated parties")
        implications.append("Review counterparty relationships for exposure to designated network")
    if "remov" in low or "delist" in low:
        implications.append("Previously blocked transactions may now be permissible — review pending matters")
        implications.append("Unblocking of assets may require OFAC reporting")
        implications.append("Monitor for related entities that may remain on SDN list")
    if "venezuela" in low or "pdvsa" in low:
        implications.append("Apply 50% rule analysis to all PdVSA-linked counterparties")
        implications.append("Review blocked vessel lists before transacting")
    if "russia" in low:
        implications.append("Secondary sanctions risk applies to non-U.S. persons — advise foreign clients")
        implications.append("EO 14024 is the primary authority — confirm applicability to transaction")
    if "iran" in low:
        implications.append("Primary and secondary sanctions both apply — distinguish U.S. and non-U.S. persons")
        implications.append("Check expiration dates carefully on any Iran-related GLs")
    if "belarus" in low:
        implications.append("Directive 1 rescission significantly changes Belarus compliance landscape")
        implications.append("Review and update Belarus compliance policies immediately")
    if not implications:
        implications = [
            "Review full action text on OFAC.treasury.gov",
            "Assess impact on existing client transactions and counterparty relationships",
            "Update internal compliance screening as needed"
        ]
    return implications[:4]

def get_coverage_dates(actions):
    if not actions:
        return "Recent", "Recent"
    dates = sorted([a["date_raw"] for a in actions])
    start = dates[0].strftime("%b %-d, %Y")
    end = dates[-1].strftime("%b %-d, %Y")
    return start, end

def rewrite_html(actions):
    with open("index.html", "r", encoding="utf-8") as f:
        content = f.read()

    js_actions = build_js_actions(actions)
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    start_date, end_date = get_coverage_dates(actions)

    # Replace ACTIONS block
    content = re.sub(
        r'/\* ACTIONS_START \*/.*?/\* ACTIONS_END \*/',
        f'/* ACTIONS_START */\n{js_actions}\n/* ACTIONS_END */',
        content, flags=re.DOTALL
    )

    # Update LAST_UPDATED
    content = re.sub(
        r'const LAST_UPDATED = "[^"]*";',
        f'const LAST_UPDATED = "{updated}";',
        content
    )

    # Update coverage period in header
    content = re.sub(
        r'<div class="header-meta-val">.*?–.*?</div>',
        f'<div class="header-meta-val">{start_date} – {end_date}</div>',
        content
    )

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(content)

    print(f"  Rewrote index.html with {len(actions)} actions")
    print(f"  Coverage: {start_date} – {end_date}")
    print(f"  Last updated: {updated}")

def main():
    all_raw = []

    fr = scrape_federal_register()
    all_raw.extend(fr)
    time.sleep(1)

    ofac = scrape_ofac()
    all_raw.extend(ofac)

    merged = merge(all_raw)
    print(f"  Total unique actions: {len(merged)}")

    if not merged:
        print("No actions found — keeping existing index.html")
        return

    rewrite_html(merged)
    print("Done.")

if __name__ == "__main__":
    main()
