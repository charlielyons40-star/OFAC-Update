#!/usr/bin/env python3
"""
OFAC Action Tracker — Daily scraper
Fetches recent actions from OFAC and the Federal Register,
then injects the data into index.html as a JS array.
"""

import json
import re
import sys
import time
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError
from html.parser import HTMLParser

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; OFAC-Tracker-Bot/1.0)"
}

PROGRAM_KEYWORDS = {
    "russia":      ["russia", "ukraine", "eo 14024", "eo14024", "gl 13", "gl 134", "russian"],
    "iran":        ["iran", "iranian", "ifsr", "irgc", "itsr"],
    "venezuela":   ["venezuela", "venezuelan", "pdvsa", "gl 52", "gl 5v"],
    "cuba":        ["cuba", "cuban", "cacr"],
    "ct":          ["hizballah", "hezbollah", "hamas", "sdgt", "terrorist", "terrorism",
                    "counterterrorism", "al-qaeda", "isis", "isil"],
    "nk":          ["north korea", "dprk", "npwmd", "kwangson", "korean"],
    "cyber":       ["cyber", "ransomware", "darkside", "evil corp", "wizard spider"],
}

TYPE_KEYWORDS = {
    "designation": ["designated", "designation", "added to the sdn", "sanctioned",
                    "blocked persons list"],
    "removal":     ["removed", "removal", "delisted", "unblocked", "delisting"],
    "license":     ["general license", "gl ", "authorized", "authorization",
                    "specific license"],
    "update":      ["updated", "update", "amended", "amendment", "modified"],
}


def fetch(url):
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=15) as r:
            return r.read().decode("utf-8", errors="replace")
    except URLError as e:
        print(f"  WARN: could not fetch {url}: {e}", file=sys.stderr)
        return ""


def classify(text):
    low = text.lower()
    types = [k for k, kws in TYPE_KEYWORDS.items() if any(w in low for w in kws)]
    programs = [k for k, kws in PROGRAM_KEYWORDS.items() if any(w in low for w in kws)]
    if not types:
        types = ["update"]
    return types, programs


def fmt_date(dt):
    return dt.strftime("%b %-d, %Y")


def ts_int(dt):
    return int(dt.strftime("%Y%m%d"))


# ── Source 1: OFAC Recent Actions page ──────────────────────────────────────

class OFACParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items = []
        self._in_item = False
        self._in_title = False
        self._in_date = False
        self._in_desc = False
        self._cur = {}
        self._buf = ""
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        adict = dict(attrs)
        cls = adict.get("class", "")
        if "views-row" in cls or "views-field-title" in cls:
            self._in_item = True
            self._cur = {"url": "https://ofac.treasury.gov/recent-actions"}
        if self._in_item:
            if tag == "h3" or ("field-content" in cls and self._buf == ""):
                self._in_title = True
            if "date" in cls or tag == "time":
                self._in_date = True
            if tag == "a" and "href" in adict:
                href = adict["href"]
                if href.startswith("/"):
                    href = "https://ofac.treasury.gov" + href
                self._cur["url"] = href
            if "field-content" in cls:
                self._in_desc = True

    def handle_data(self, data):
        data = data.strip()
        if not data:
            return
        if self._in_title and not self._cur.get("title"):
            self._cur["title"] = data
            self._in_title = False
        elif self._in_date and not self._cur.get("date"):
            self._cur["date"] = data
            self._in_date = False
        elif self._in_desc and not self._cur.get("desc"):
            self._cur["desc"] = data

    def handle_endtag(self, tag):
        if tag in ("article", "li") and self._cur.get("title"):
            self.items.append(self._cur)
            self._cur = {}
            self._in_item = False


def scrape_ofac():
    print("Fetching OFAC recent actions page…")
    html = fetch("https://ofac.treasury.gov/recent-actions")
    if not html:
        return []

    # Extract action blocks via regex (OFAC page structure varies)
    actions = []
    # Look for date + title patterns in the HTML
    # Pattern: date heading followed by action descriptions
    date_pattern = re.compile(
        r'(\d{1,2}/\d{1,2}/\d{4}|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2},?\s+\d{4})',
        re.IGNORECASE
    )
    title_pattern = re.compile(r'<(?:h[1-6]|strong|b)[^>]*>(.*?)</(?:h[1-6]|strong|b)>', re.DOTALL)
    link_pattern = re.compile(r'href="(/[^"]+)"[^>]*>([^<]{10,})</a>')

    titles_found = title_pattern.findall(html)
    links_found = link_pattern.findall(html)

    seen = set()
    for href, text in links_found:
        text = re.sub(r'<[^>]+>', '', text).strip()
        if len(text) < 15 or text in seen:
            continue
        if any(skip in href.lower() for skip in ['login', 'search', 'about', 'contact']):
            continue
        seen.add(text)
        url = "https://ofac.treasury.gov" + href
        types, programs = classify(text)
        actions.append({
            "title": text,
            "desc": text,
            "url": url,
            "types": types,
            "programs": programs,
            "date_raw": datetime.now(timezone.utc)
        })
        if len(actions) >= 20:
            break

    return actions


# ── Source 2: Federal Register OFAC notices ─────────────────────────────────

def scrape_federal_register():
    print("Fetching Federal Register OFAC notices…")
    url = (
        "https://www.federalregister.gov/api/v1/documents.json"
        "?conditions[agencies][]=office-of-foreign-assets-control"
        "&conditions[type][]=Notice"
        "&order=newest"
        "&per_page=20"
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
            "url": html_url,
            "types": types,
            "programs": programs,
            "date_raw": dt,
        })

    return actions


# ── Source 3: ABA Banking Journal OFAC roundup ──────────────────────────────

def scrape_aba():
    print("Fetching ABA Banking Journal OFAC roundup…")
    html = fetch("https://bankingjournal.aba.com/?s=ofac")
    if not html:
        return []

    actions = []
    pattern = re.compile(
        r'<h[23][^>]*>\s*<a\s+href="([^"]+)"[^>]*>(.*?)</a>\s*</h[23]>',
        re.DOTALL | re.IGNORECASE
    )
    date_pat = re.compile(r'(\d{4}/\d{2}/\d{2})')

    for m in pattern.finditer(html):
        url, title = m.group(1), re.sub(r'<[^>]+>', '', m.group(2)).strip()
        if "ofac" not in url.lower() and "ofac" not in title.lower():
            continue
        dm = date_pat.search(url)
        if dm:
            try:
                dt = datetime.strptime(dm.group(1), "%Y/%m/%d").replace(tzinfo=timezone.utc)
            except ValueError:
                dt = datetime.now(timezone.utc)
        else:
            dt = datetime.now(timezone.utc)

        types, programs = classify(title)
        actions.append({
            "title": title,
            "desc": title,
            "url": url,
            "types": types,
            "programs": programs,
            "date_raw": dt,
        })
        if len(actions) >= 10:
            break

    return actions


# ── Merge, deduplicate, sort ─────────────────────────────────────────────────

def normalise(s):
    return re.sub(r'\W+', ' ', s.lower()).strip()


def merge(sources):
    seen_titles = set()
    merged = []
    for item in sources:
        key = normalise(item["title"])[:60]
        if key in seen_titles:
            continue
        seen_titles.add(key)
        merged.append(item)
    merged.sort(key=lambda x: x["date_raw"], reverse=True)
    return merged[:40]


# ── Build JS-safe action objects ─────────────────────────────────────────────

def build_actions(raw):
    actions = []
    for i, item in enumerate(raw, 1):
        dt = item["date_raw"]
        actions.append({
            "id": i,
            "date": fmt_date(dt),
            "ts": ts_int(dt),
            "title": item["title"],
            "desc": item["desc"] or item["title"],
            "types": item["types"],
            "programs": item["programs"],
            "implications": [],   # kept empty; future: LLM enrichment
            "url": item["url"],
        })
    return actions


# ── Inject into index.html ────────────────────────────────────────────────────

MARKER_START = "/* ACTIONS_START */"
MARKER_END   = "/* ACTIONS_END */"
UPDATED_MARKER = "/* LAST_UPDATED */"


def inject(html_path, actions):
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()

    js_array = "const ACTIONS = " + json.dumps(actions, ensure_ascii=False, indent=2) + ";"
    block = f"{MARKER_START}\n{js_array}\n{MARKER_END}"

    updated_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    updated_line = f'{UPDATED_MARKER}\nconst LAST_UPDATED = "{updated_str}";'

    if MARKER_START in content and MARKER_END in content:
        content = re.sub(
            re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END),
            block,
            content,
            flags=re.DOTALL
        )
    else:
        # First run: inject before closing </script>
        content = content.replace("const ACTIONS = [", block.split("\n")[1], 1)

    if UPDATED_MARKER in content:
        content = re.sub(
            re.escape(UPDATED_MARKER) + r".*?\n",
            updated_line + "\n",
            content,
            flags=re.DOTALL
        )

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"  Wrote {len(actions)} actions to {html_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    all_raw = []

    fr = scrape_federal_register()
    print(f"  → {len(fr)} items from Federal Register")
    all_raw.extend(fr)
    time.sleep(1)

    aba = scrape_aba()
    print(f"  → {len(aba)} items from ABA Banking Journal")
    all_raw.extend(aba)
    time.sleep(1)

    ofac = scrape_ofac()
    print(f"  → {len(ofac)} items from OFAC")
    all_raw.extend(ofac)

    merged = merge(all_raw)
    print(f"  → {len(merged)} unique actions after dedup")

    actions = build_actions(merged)
    inject("index.html", actions)
    print("Done.")


if __name__ == "__main__":
    main()
