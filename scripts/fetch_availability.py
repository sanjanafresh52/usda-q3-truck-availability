"""
fetch_availability.py
=====================
Pulls Q3 (July-September) refrigerated-truck availability data from the
USDA AMS Specialty Crops Program via Socrata at agtransport.usda.gov
(dataset acar-e3r8 — "Refrigerated Truck Rates and Availability").

Availability is reported weekly per lane on a 1-5 ordinal scale:
  1 = Surplus, 2 = Slight Surplus, 3 = Adequate,
  4 = Slight Shortage, 5 = Shortage
(Higher = tighter capacity.)

Output: data/q3_availability.json — mean Q3 availability by region &
commodity, 4-year average. No API key required.
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

SOCRATA_DOMAIN = "agtransport.usda.gov"
DATASET_ID = "acar-e3r8"
API_URL = f"https://{SOCRATA_DOMAIN}/resource/{DATASET_ID}.json"

N_YEARS = 4
Q3_MONTHS = (7, 8, 9)
PAGE_SIZE = 10_000
TOP_N_COMMODITIES = 30  # ranked by row count; this dataset has no volume column

KNOWN_REGIONS: list[str] = [
    "Arizona", "California", "Colorado", "Florida", "Great Lakes",
    "Mexico-Arizona", "Mexico-California", "Mexico-New Mexico", "Mexico-Texas",
    "Mid-Atlantic", "New York", "PNW", "Southeast", "Texas",
]

AVAILABILITY_LABELS = {
    1: "Surplus",
    2: "Slight Surplus",
    3: "Adequate",
    4: "Slight Shortage",
    5: "Shortage",
}


def get_app_token() -> str | None:
    return os.environ.get("SOCRATA_APP_TOKEN") or None


def _get_with_retry(
    url: str,
    *,
    params: dict[str, Any],
    headers: dict[str, str],
    timeout: int,
    max_retries: int = 5,
) -> requests.Response:
    retryable = (
        requests.exceptions.Timeout,
        requests.exceptions.ConnectionError,
        requests.exceptions.ChunkedEncodingError,
    )
    for attempt in range(max_retries + 1):
        try:
            return requests.get(url, params=params, headers=headers, timeout=timeout)
        except retryable as e:
            if attempt == max_retries:
                raise
            backoff = 2 ** (attempt + 1)
            print(f"\n    {type(e).__name__} on attempt {attempt + 1}/{max_retries + 1}; "
                  f"retrying in {backoff}s …", flush=True)
            time.sleep(backoff)
            print(f"  → page offset={params.get('$offset', 0):>7} (retry) ", end="", flush=True)
    raise RuntimeError("unreachable")


def fetch_all(start_year: int, end_year: int) -> list[dict[str, Any]]:
    headers: dict[str, str] = {}
    token = get_app_token()
    if token:
        headers["X-App-Token"] = token

    rows: list[dict[str, Any]] = []
    offset = 0
    # acar-e3r8 carries `date` directly, plus pre-extracted `month` and `year`
    # text columns. We push the Q3 + year-range predicate into $where so Socrata
    # drops ~75% of rows before they hit the wire.
    where = (
        f"date_extract_m(date) IN (7, 8, 9) AND "
        f"date_extract_y(date) BETWEEN {start_year} AND {end_year}"
    )

    while True:
        params: dict[str, Any] = {
            "$limit": PAGE_SIZE,
            "$offset": offset,
            "$order": ":id",
            "$where": where,
        }
        print(f"  → page offset={offset:>7} ", end="", flush=True)
        r = _get_with_retry(API_URL, params=params, headers=headers, timeout=300)
        if r.status_code != 200:
            print(f"HTTP {r.status_code}: {r.text[:200]}")
            sys.exit(1)
        batch = r.json()
        print(f"({len(batch):>5} rows)")
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += len(batch)
        if offset > 5_000_000:
            print("    safety cap hit; stopping.")
            break

    return rows


_GREAT_LAKES = {"GREAT LAKES", "MICHIGAN", "WISCONSIN", "MINNESOTA", "OHIO", "INDIANA", "ILLINOIS"}
_MID_ATLANTIC = {"MID-ATLANTIC", "PENNSYLVANIA", "NEW JERSEY", "DELAWARE", "MARYLAND",
                 "VIRGINIA", "WEST VIRGINIA"}
_SOUTHEAST = {"SOUTHEAST", "NORTH CAROLINA", "SOUTH CAROLINA", "GEORGIA", "ALABAMA",
              "TENNESSEE", "KENTUCKY"}
_PNW = {"PNW", "PACIFIC NORTHWEST", "WASHINGTON", "OREGON", "IDAHO"}


def normalize_region(raw: str) -> str | None:
    u = raw.strip().upper()
    if not u:
        return None
    if u.startswith("MEXICO-CALIFORNIA"):
        return "Mexico-California"
    if u.startswith("MEXICO-ARIZONA"):
        return "Mexico-Arizona"
    if u.startswith("MEXICO-TEXAS"):
        return "Mexico-Texas"
    if u.startswith("MEXICO-NEW MEXICO") or u.startswith("MEXICO-NM"):
        return "Mexico-New Mexico"
    if u.startswith("CALIFORNIA"):
        return "California"
    if u in _PNW:
        return "PNW"
    if u == "ARIZONA":
        return "Arizona"
    if u == "COLORADO":
        return "Colorado"
    if u == "FLORIDA":
        return "Florida"
    if u == "NEW YORK":
        return "New York"
    if u == "TEXAS":
        return "Texas"
    if u in _GREAT_LAKES:
        return "Great Lakes"
    if u in _MID_ATLANTIC:
        return "Mid-Atlantic"
    if u in _SOUTHEAST:
        return "Southeast"
    return None


def parse_date(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {"availability": {}, "commodities": [], "regions": []}

    # acar-e3r8 schema is fixed; no need for auto-detection like the volumes
    # dataset (rfpn-7etz, where AMS occasionally renames fields).
    region_counts = Counter(
        (rec.get("region") or "").strip() for rec in records
        if (rec.get("region") or "").strip()
    )
    print(f"  raw region labels (of {len(region_counts)} unique):")
    for label, n in region_counts.most_common(30):
        print(f"    {n:>7,}  {label}  → {normalize_region(label)}")

    # acc[commodity][region][year][month] = list of availability scores
    acc: dict[str, dict[str, dict[int, dict[int, list[int]]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    )

    kept = 0
    skipped_bad_avail = 0
    for rec in records:
        d = parse_date(rec.get("date", ""))
        if d is None or d.month not in Q3_MONTHS:
            continue
        region = normalize_region(rec.get("region") or "")
        commodity = (rec.get("commodity") or "").strip()
        if not region or not commodity:
            continue
        try:
            avail = int(rec.get("availability", ""))
        except (TypeError, ValueError):
            skipped_bad_avail += 1
            continue
        if avail < 1 or avail > 5:
            skipped_bad_avail += 1
            continue
        acc[commodity][region][d.year][d.month].append(avail)
        kept += 1

    print(f"  kept {kept:,} Q3 records ({skipped_bad_avail:,} dropped for bad availability) "
          f"→ {len(acc)} commodities × {len({r for c in acc.values() for r in c})} regions")

    # availability[commodity][region] = {jul, aug, sep, n_jul, n_aug, n_sep}
    availability: dict[str, dict[str, dict[str, float]]] = {}
    commodity_row_counts: Counter = Counter()
    for commodity, regions in acc.items():
        availability[commodity] = {}
        for region, by_year in regions.items():
            # Collect all scores per Q3 month across the year window, then take
            # the mean. Equivalent to averaging year-means when each year has
            # roughly the same number of reports, and more robust when some
            # years have sparse coverage.
            month_scores: dict[int, list[int]] = {7: [], 8: [], 9: []}
            for year_data in by_year.values():
                for m in Q3_MONTHS:
                    month_scores[m].extend(year_data.get(m, []))
            commodity_row_counts[commodity] += sum(len(v) for v in month_scores.values())
            availability[commodity][region] = {
                "jul": round(sum(month_scores[7]) / len(month_scores[7]), 2) if month_scores[7] else None,
                "aug": round(sum(month_scores[8]) / len(month_scores[8]), 2) if month_scores[8] else None,
                "sep": round(sum(month_scores[9]) / len(month_scores[9]), 2) if month_scores[9] else None,
                "n_jul": len(month_scores[7]),
                "n_aug": len(month_scores[8]),
                "n_sep": len(month_scores[9]),
            }

    # Keep the top N commodities by report count — this dataset has no volume
    # column, so coverage is the most defensible ranking. Past ~30, regions
    # have <5 reports per month and the means get noisy.
    top_commodities = [c for c, _ in commodity_row_counts.most_common(TOP_N_COMMODITIES)]
    availability = {c: availability[c] for c in top_commodities}

    # "All Commodities" rollup — unweighted mean over every (region, q3 month)
    # row in the original data, regardless of whether the commodity made the
    # top-N list. This is the right denominator: capacity tightness is a lane
    # property, not a commodity one.
    all_scores: dict[str, dict[int, list[int]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for commodity, regions in acc.items():
        for region, by_year in regions.items():
            for year_data in by_year.values():
                for m, scores in year_data.items():
                    all_scores[region][m].extend(scores)

    all_c: dict[str, dict[str, float]] = {}
    for region, by_month in all_scores.items():
        all_c[region] = {
            "jul": round(sum(by_month[7]) / len(by_month[7]), 2) if by_month.get(7) else None,
            "aug": round(sum(by_month[8]) / len(by_month[8]), 2) if by_month.get(8) else None,
            "sep": round(sum(by_month[9]) / len(by_month[9]), 2) if by_month.get(9) else None,
            "n_jul": len(by_month.get(7, [])),
            "n_aug": len(by_month.get(8, [])),
            "n_sep": len(by_month.get(9, [])),
        }
    availability = {"All Commodities": all_c, **availability}

    all_regions = sorted({r for c in availability.values() for r in c})
    return {
        "availability": availability,
        "commodities": list(availability.keys()),
        "regions": all_regions,
    }


def main() -> None:
    now = datetime.now()
    end_year = now.year - 1
    start_year = end_year - (N_YEARS - 1)

    print(f"Fetching AMS Refrigerated Truck Rates & Availability ({DATASET_ID}) for {start_year}–{end_year} …")
    records = fetch_all(start_year, end_year)
    print(f"  total raw rows: {len(records):,}\n")

    print("Aggregating Q3 (Jul–Sep) by commodity × region …")
    agg = aggregate(records)

    out = {
        "metadata": {
            "source": f"USDA AMS Specialty Crops Movement Reports (Socrata: {SOCRATA_DOMAIN}/resource/{DATASET_ID})",
            "years": [str(y) for y in range(start_year, end_year + 1)],
            "n_years_avg": N_YEARS,
            "metric": "Refrigerated truck availability, Q3 (Jul-Sep) mean on 1-5 scale (1=Surplus, 5=Shortage)",
            "scale": AVAILABILITY_LABELS,
            "fetched_at": now.isoformat(),
        },
        "availability": agg["availability"],
        "commodities": agg["commodities"],
        "regions": agg["regions"],
        "known_regions": KNOWN_REGIONS,
    }

    out_path = Path(__file__).resolve().parent.parent / "data" / "q3_availability.json"
    out_path.parent.mkdir(exist_ok=True, parents=True)
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\n✓ Wrote {out_path}")


if __name__ == "__main__":
    main()
