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
commodity, **broken down by week-of-year** across a 4-year window. The
dashboard draws one line per region using these weekly points, with a
dashed reference at score = 3 (Adequate).
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
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


def week_anchor_date(year: int, iso_week: int) -> datetime:
    """Monday of the given ISO week. Used to produce a stable x-axis label
    for each week bucket regardless of which year's data fell into it."""
    # `fromisocalendar` requires a valid weekday; Monday = 1.
    return datetime.fromisocalendar(year, iso_week, 1)


def aggregate(records: list[dict[str, Any]], end_year: int) -> dict[str, Any]:
    if not records:
        return {"availability": {}, "commodities": [], "regions": [], "weeks": []}

    region_counts = Counter(
        (rec.get("region") or "").strip() for rec in records
        if (rec.get("region") or "").strip()
    )
    print(f"  raw region labels (of {len(region_counts)} unique):")
    for label, n in region_counts.most_common(30):
        print(f"    {n:>7,}  {label}  → {normalize_region(label)}")

    # acc[commodity][region][iso_week] = list of availability scores
    acc: dict[str, dict[str, dict[int, list[int]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    weeks_seen: set[int] = set()

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
        iso_week = d.isocalendar().week
        acc[commodity][region][iso_week].append(avail)
        weeks_seen.add(iso_week)
        kept += 1

    print(f"  kept {kept:,} Q3 records ({skipped_bad_avail:,} dropped for bad availability) "
          f"→ {len(acc)} commodities × {len({r for c in acc.values() for r in c})} regions "
          f"× {len(weeks_seen)} ISO weeks")

    # Build the canonical weeks list. Anchor each week to its Monday in
    # `end_year` so the x-axis labels read like a single representative year
    # ("Jul 7", "Jul 14", …) rather than smearing across the 4-year window.
    weeks_sorted = sorted(weeks_seen)
    weeks_out: list[dict[str, Any]] = []
    for w in weeks_sorted:
        try:
            anchor = week_anchor_date(end_year, w)
        except ValueError:
            # ISO week doesn't exist in end_year (e.g. week 53). Fall back to
            # the most recent year that has that week.
            for y in range(end_year, end_year - N_YEARS, -1):
                try:
                    anchor = week_anchor_date(y, w)
                    break
                except ValueError:
                    continue
            else:
                continue
        weeks_out.append({
            "w": w,
            "label": anchor.strftime("%b %d"),
            # ms epoch for the Monday; lets D3 use a true time scale
            # if we ever want to, without re-deriving from the label.
            "t": int(anchor.timestamp() * 1000),
        })

    # availability[commodity][region][week] = {"score": ..., "n": ...}
    availability: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
    commodity_row_counts: Counter = Counter()
    for commodity, regions in acc.items():
        availability[commodity] = {}
        for region, by_week in regions.items():
            availability[commodity][region] = {}
            for w, scores in by_week.items():
                if not scores:
                    continue
                availability[commodity][region][str(w)] = {
                    "score": round(sum(scores) / len(scores), 2),
                    "n": len(scores),
                }
                commodity_row_counts[commodity] += len(scores)

    # Keep top-N commodities by report count.
    top_commodities = [c for c, _ in commodity_row_counts.most_common(TOP_N_COMMODITIES)]
    availability = {c: availability[c] for c in top_commodities}

    # "All Commodities" rollup — every Q3 record, regardless of commodity.
    all_acc: dict[str, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    for commodity, regions in acc.items():
        for region, by_week in regions.items():
            for w, scores in by_week.items():
                all_acc[region][w].extend(scores)
    all_c: dict[str, dict[str, dict[str, float]]] = {}
    for region, by_week in all_acc.items():
        all_c[region] = {
            str(w): {"score": round(sum(s) / len(s), 2), "n": len(s)}
            for w, s in by_week.items() if s
        }
    availability = {"All Commodities": all_c, **availability}

    all_regions = sorted({r for c in availability.values() for r in c})
    return {
        "availability": availability,
        "commodities": list(availability.keys()),
        "regions": all_regions,
        "weeks": weeks_out,
    }


def main() -> None:
    now = datetime.now()
    end_year = now.year - 1
    start_year = end_year - (N_YEARS - 1)

    print(f"Fetching AMS Refrigerated Truck Rates & Availability ({DATASET_ID}) for {start_year}–{end_year} …")
    records = fetch_all(start_year, end_year)
    print(f"  total raw rows: {len(records):,}\n")

    print("Aggregating Q3 (Jul–Sep) by commodity × region × week …")
    agg = aggregate(records, end_year)

    out = {
        "metadata": {
            "source": f"USDA AMS Specialty Crops Movement Reports (Socrata: {SOCRATA_DOMAIN}/resource/{DATASET_ID})",
            "years": [str(y) for y in range(start_year, end_year + 1)],
            "n_years_avg": N_YEARS,
            "metric": "Refrigerated truck availability, weekly mean across Q3 (1=Surplus, 5=Shortage)",
            "scale": AVAILABILITY_LABELS,
            "fetched_at": now.isoformat(),
        },
        "weeks": agg["weeks"],
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
