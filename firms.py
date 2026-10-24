"""
JALYN — NASA FIRMS satellite data → flares.

The idea (the same one behind the World Bank's Global Gas Flaring Tracker): VIIRS
satellites (Suomi NPP, NOAA-20, NOAA-21) record thermal anomalies on the ground every
night. A wildfire lives a few days and moves; a flare burns in one spot for months.
So we take N nights of detections, put them on a grid and keep the cells that light up
on most nights.

FIRMS Area API: https://firms.modaps.eosdis.nasa.gov/api/area/
Format: /api/area/csv/{MAP_KEY}/{SOURCE}/{west,south,east,north}/{days 1..10}/{YYYY-MM-DD}
The key is free and takes a minute to get.
"""

from __future__ import annotations

import csv
import io
import logging
import time
from collections import defaultdict
from datetime import date, timedelta

import httpx

log = logging.getLogger("jalyn.firms")

FIRMS_BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
# Kazakhstan bounding box: west, south, east, north
KAZAKHSTAN_BBOX = "46.5,40.5,87.4,55.5"
DEFAULT_SOURCES = ("VIIRS_NOAA20_NRT", "VIIRS_SNPP_NRT")

# Coarse region lookup (oil-producing regions of the west and south)
REGIONS = [
    ("Mangystau region", 50.0, 56.0, 41.5, 46.1),
    ("Atyrau region", 48.5, 55.5, 46.1, 49.0),
    ("West Kazakhstan region", 48.5, 55.0, 49.0, 52.0),
    ("Aktobe region", 55.0, 62.0, 46.0, 51.5),
    ("Kyzylorda region", 59.5, 67.0, 43.5, 47.0),
    ("Turkistan region", 66.0, 72.0, 40.5, 44.5),
    ("Karaganda / Ulytau", 62.0, 78.0, 46.0, 51.0),
]


def region_for(lat: float, lon: float) -> str:
    for name, w, e, s, n in REGIONS:
        if w <= lon <= e and s <= lat <= n:
            return name
    return "Kazakhstan"


def _date_windows(days: int) -> list[tuple[str, int]]:
    """Split the period into windows of ≤10 days (API limit)."""
    windows = []
    end = date.today()
    start = end - timedelta(days=days)
    cursor = start
    while cursor < end:
        n = min(10, (end - cursor).days)
        windows.append((cursor.isoformat(), n))
        cursor += timedelta(days=n)
    return windows


def fetch_detections(map_key: str, days: int = 60, bbox: str = KAZAKHSTAN_BBOX,
                     sources: tuple[str, ...] = DEFAULT_SOURCES, night_only: bool = True) -> list[dict]:
    """Download detections for `days` days from every source. Returns a list of dicts."""
    rows: list[dict] = []
    with httpx.Client(timeout=60) as client:
        for source in sources:
            for start, n in _date_windows(days):
                url = f"{FIRMS_BASE}/{map_key}/{source}/{bbox}/{n}/{start}"
                try:
                    r = client.get(url)
                    r.raise_for_status()
                except httpx.HTTPError as exc:
                    log.warning("FIRMS request failed (%s %s): %s", source, start, exc)
                    continue
                text = r.text.strip()
                if not text or text.lower().startswith("invalid"):
                    log.warning("FIRMS returned no data for %s %s: %s", source, start, text[:80])
                    continue
                for rec in csv.DictReader(io.StringIO(text)):
                    if night_only and rec.get("daynight", "N") != "N":
                        continue
                    try:
                        rows.append(
                            {
                                "lat": float(rec["latitude"]),
                                "lon": float(rec["longitude"]),
                                "frp": float(rec.get("frp") or 0),
                                "date": rec["acq_date"],
                                "source": source,
                            }
                        )
                    except (KeyError, ValueError):
                        continue
    log.info("FIRMS: %d night detections over %d days", len(rows), days)
    return rows


def cluster_persistent(detections: list[dict], days: int, cell_deg: float = 0.015,
                       min_persistence: float = 0.35, min_nights: int = 8) -> list[dict]:
    """Grid → persistent cells = flares.

    cell_deg 0.015° ≈ 1.5 km: a flare with its geolocation jitter lands in one cell.
    min_persistence — share of nights with a detection; min_nights — guard for short windows.
    """
    cells: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for d in detections:
        key = (round(d["lat"] / cell_deg), round(d["lon"] / cell_deg))
        cells[key].append(d)

    sites = []
    for key, dets in cells.items():
        nights = {d["date"] for d in dets}
        persistence = len(nights) / max(days, 1)
        if persistence < min_persistence or len(nights) < min_nights:
            continue
        lat = sum(d["lat"] for d in dets) / len(dets)
        lon = sum(d["lon"] for d in dets) / len(dets)
        frps = [d["frp"] for d in dets if d["frp"] > 0]
        frp_mean = sum(frps) / len(frps) if frps else 0.0
        region = region_for(lat, lon)
        sites.append(
            {
                "id": f"L-{abs(key[0])}-{abs(key[1])}",
                "name": f"Flare {region.split(' ')[0]} {abs(key[0]) % 97:02d}-{abs(key[1]) % 89:02d}",
                "region": region,
                "lat": round(lat, 4),
                "lon": round(lon, 4),
                "nights_detected": len(nights),
                "nights_total": days,
                "persistence": round(persistence, 2),
                "frp_mean_mw": round(frp_mean, 2),
                "frp_max_mw": round(max(frps), 2) if frps else 0.0,
                "detections": len(dets),
                "source": "NASA FIRMS (VIIRS NRT)",
            }
        )
    sites.sort(key=lambda s: s["frp_mean_mw"] * s["persistence"], reverse=True)
    return sites


class FlareCache:
    """Small cache so that every browser request does not hit FIRMS."""

    def __init__(self, ttl_seconds: int = 6 * 3600):
        self.ttl = ttl_seconds
        self._data: dict[int, tuple[float, list[dict]]] = {}

    def get(self, days: int) -> list[dict] | None:
        item = self._data.get(days)
        if not item:
            return None
        ts, sites = item
        if time.time() - ts > self.ttl:
            return None
        return sites

    def put(self, days: int, sites: list[dict]) -> None:
        self._data[days] = (time.time(), sites)
