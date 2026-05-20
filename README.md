# Q3 Reefer Truck Availability — USDA AMS

Automated **line graph** of weekly refrigerated-truck availability across Q3 (Jul–Sep). Availability is the AMS weekly market rating on a 1–5 scale (1 = Surplus, 5 = Shortage); the chart shows the **report-weighted average across the regions you select**, with a dashed reference at **3 (Adequate)** so weeks above/below the threshold are easy to spot. Two lines total: the average and the threshold. Data is pulled live from the USDA AMS Refrigerated Truck Rates and Availability dataset (Socrata `acar-e3r8`) and publishes to GitHub Pages — drop the URL into your Q3 customer report as an iframe.

**Live URL:** `https://<your-username>.github.io/usda-q3-truck-availability/`

Companion to the volumes heat map (`usda-q3-dashboard`). Volumes answer "where is the produce coming from"; this answers "and how hard is it to move it out of there each week."

---

## Setup (5 minutes)

1. **Push this repo to GitHub.**
2. **Settings → Pages → Source: GitHub Actions.**
3. *(Optional)* **Settings → Secrets → Actions → New repository secret** named `SOCRATA_APP_TOKEN`. Not required — the AMS dataset is public — but a token raises your rate limit. Free token: https://data.socrata.com/profile/app_tokens
4. **Actions → Build Q3 Availability Dashboard → Run workflow.**

After ~90 seconds the chart publishes at your Pages URL.

---

## What it does

1. Pulls every Q3 (Jul/Aug/Sep) row from the **AMS Refrigerated Truck Rates and Availability** dataset for the last 4 complete calendar years.
2. Aggregates the mean availability score by **commodity × USDA shipping region × ISO week**.
3. **Combines** the selected regions into a single weekly average — each region's weekly score is weighted by its lane-week report count, so a region with 200 reports counts more than one with 5. Renders that average as a single line, with a dashed reference at **score = 3** dividing the surplus zone (below) from the shortage zone (above).
4. **Filters:**
   - **Commodity** — top 30 by report count plus an "All Commodities" rollup.
   - **Regions** — multi-select chips. Mexico crossings start off; click to include. "All" / "None" buttons for fast toggling. Changing the region selection re-aggregates the line.
5. **Hover** anywhere on the chart for the week's average score, ordinal label, contributing region count, and total report count.

---

## Availability scale

| Score | Label |
|------:|:------|
| 1 | Surplus |
| 2 | Slight Surplus |
| 3 | Adequate *(reference threshold)* |
| 4 | Slight Shortage |
| 5 | Shortage |

The week-of-Q3 buckets use ISO week numbers; x-axis labels are anchored to the **Monday of each ISO week in the most-recent year** so the labels read like a single representative calendar (e.g., "Jul 7", "Jul 14") rather than smearing across the 4-year window.

---

## Repo layout

```
.github/workflows/build.yml         Manual-trigger workflow → deploys to Pages
scripts/fetch_availability.py       AMS Socrata client; writes data/q3_availability.json
scripts/build_dashboard.py          Jinja2 render → docs/index.html
templates/template.html.j2          Line chart (D3) + chip controls
data/q3_availability.json           Latest cached fetch (auto-committed by CI)
docs/index.html                     Generated dashboard (published)
requirements.txt                    requests + jinja2
```

---

## Local development

```bash
pip install -r requirements.txt
python scripts/fetch_availability.py    # pulls fresh data
python scripts/build_dashboard.py       # renders HTML
# Open docs/index.html
```

---

## Customization

- **Average line color:** the `--accent` CSS variable at the top of the template (defaults to Mango Tango #ec7700).
- **Threshold line:** change `const THRESHOLD = 3;` in the template.
- **Weighted vs unweighted average:** the `aggregateWeekly()` function in the template uses `sum += score * n; total_n += n;` — drop the `* n` and divide by region count to switch to an unweighted mean.
- **Top-N commodities:** the script keeps the top 30 by report count; bump `TOP_N_COMMODITIES` in `fetch_availability.py` if you want more.
- **Different time window:** change `N_YEARS` or `Q3_MONTHS` in `fetch_availability.py`.

---

## Data source

- **Dataset:** USDA AMS Specialty Crops Program — Refrigerated Truck Rates and Availability
- **URL:** https://agtransport.usda.gov/Truck/Refrigerated-Truck-Rates-and-Availability/acar-e3r8/data
- **Owner:** USDA AMS Transportation Services Division
- **Updated:** weekly
- **API:** Socrata SODA v2 — `https://agtransport.usda.gov/resource/acar-e3r8.json`
- **Coding:** 1 (Surplus) to 5 (Shortage), integer per lane-week
