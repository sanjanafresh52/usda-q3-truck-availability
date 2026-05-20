# Q3 Reefer Truck Availability Heat Map — USDA AMS

Automated US heat map of Q3 (July–September) refrigerated truck **availability** by USDA shipping region. Availability is the weekly market rating AMS publishes on a 1–5 scale where 1 = Surplus (lots of trucks) and 5 = Shortage (capacity tight). Data is pulled live from the USDA AMS Refrigerated Truck Rates and Availability dataset (Socrata `acar-e3r8`) and publishes to GitHub Pages — drop the URL into your Q3 customer report as an iframe.

**Live URL:** `https://<your-username>.github.io/usda-q3-truck-availability/`

This is the companion report to the volumes heat map (`usda-q3-dashboard`). Volumes answer "where is the produce coming from"; availability answers "how hard is it to move it out of there."

---

## Setup (5 minutes)

1. **Push this repo to GitHub.**
2. **Settings → Pages → Source: GitHub Actions.**
3. *(Optional)* **Settings → Secrets → Actions → New repository secret** named `SOCRATA_APP_TOKEN` if you have one. Not required — the AMS dataset is public — but a token raises your rate limit. Free token: https://data.socrata.com/profile/app_tokens
4. **Actions → Build Q3 Availability Dashboard → Run workflow.**

After ~90 seconds the heat map publishes at your Pages URL.

---

## What it does

1. Pulls every Q3 (Jul/Aug/Sep) row from the **AMS Refrigerated Truck Rates and Availability** dataset for the last 4 complete calendar years.
2. Aggregates the mean **availability score** by **commodity × USDA shipping region × Q3 month** (Arizona, California, Colorado, Florida, Great Lakes, Mid-Atlantic, New York, PNW, Southeast, Texas, plus Mexico-AZ / -CA / -NM / -TX crossings).
3. Renders a **choropleth US map** (Census Bureau state boundaries via TopoJSON, Albers projection) with a cream → dark burnt-orange ramp — darker = tighter capacity.
4. **Two filters:** commodity (top 30 by report-count + "All Commodities" rollup) and Q3 month (Full Q3 / Jul / Aug / Sep). Map recolors on each change.
5. **Hover** any state for `{state} · {region} · {score} · {label} (n=reports)`. Hover Mexico boxes for cross-border availability.

---

## Availability scale

| Score | Label |
|------:|:------|
| 1 | Surplus |
| 2 | Slight Surplus |
| 3 | Adequate |
| 4 | Slight Shortage |
| 5 | Shortage |

The "Full Q3" rollup uses a report-count-weighted mean across Jul/Aug/Sep so a month with few observations doesn't drown out a month with many. The "All Commodities" rollup is the unweighted mean of every lane-week in that region/month — capacity tightness is a lane property, not a commodity one.

---

## Repo layout

```
.github/workflows/build.yml         Manual-trigger workflow → deploys to Pages
scripts/fetch_availability.py       AMS Socrata API client; writes data/q3_availability.json
scripts/build_dashboard.py          Jinja2 render → docs/index.html
templates/template.html.j2          Map + controls (D3 + TopoJSON)
data/q3_availability.json           Latest cached fetch
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

- **Change region → state mapping:** edit `STATE_TO_REGION` near the top of the `<script>` in `templates/template.html.j2`.
- **Restyle:** all colors are CSS variables at the top of the template (`--heat-0` … `--heat-7`).
- **Top-N commodities:** the script keeps the top 30 by report count; bump `TOP_N_COMMODITIES` in `fetch_availability.py` if you want more. (Past ~30 individual commodities have <5 reports/month per region and the means get noisy.)
- **Different time window:** change `N_YEARS` or `Q3_MONTHS` in `fetch_availability.py`.

---

## Data source

- **Dataset:** USDA AMS Specialty Crops Program — Refrigerated Truck Rates and Availability
- **URL:** https://agtransport.usda.gov/Truck/Refrigerated-Truck-Rates-and-Availability/acar-e3r8/data
- **Owner:** USDA AMS Transportation Services Division
- **Updated:** weekly
- **API:** Socrata SODA v2 — `https://agtransport.usda.gov/resource/acar-e3r8.json`
- **Coding:** 1 (Surplus) to 5 (Shortage), integer per lane-week
