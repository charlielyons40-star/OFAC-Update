# OFAC Action Tracker

A self-updating dashboard for OFAC sanctions actions: designations, removals, and general licenses.

## How it works

- `index.html` — the single-file web app (open in any browser)
- `scrape.py` — fetches latest actions from the Federal Register and ABA Banking Journal
- `.github/workflows/update.yml` — runs the scraper automatically every weekday at 8am ET

## Setup

### 1. Create a GitHub repository
- Go to [github.com](https://github.com) and sign in (or create a free account)
- Click **New repository**
- Name it `ofac-tracker`
- Set it to **Public** (required for free GitHub Pages)
- Click **Create repository**

### 2. Upload these files
Upload all three files/folders to the repo:
- `index.html`
- `scrape.py`
- `.github/workflows/update.yml`

You can drag and drop them on the GitHub website.

### 3. Enable GitHub Pages
- Go to your repo → **Settings** → **Pages**
- Under "Source", select **Deploy from a branch**
- Choose **main** branch, **/ (root)** folder
- Click **Save**

Your tracker will be live at: `https://YOUR-USERNAME.github.io/ofac-tracker`

### 4. Enable the workflow
- Go to your repo → **Actions** tab
- Click **"I understand my workflows, go ahead and enable them"**
- The scraper will now run automatically every weekday at 8am ET

### 5. Run it manually (optional)
- Go to **Actions** → **Update OFAC Actions** → **Run workflow**

## Data sources
- [Federal Register](https://www.federalregister.gov) — official OFAC notices
- [ABA Banking Journal](https://bankingjournal.aba.com) — OFAC weekly roundups
- [OFAC Recent Actions](https://ofac.treasury.gov/recent-actions) — direct Treasury feed
