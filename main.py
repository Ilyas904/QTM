"""
JALYN — API. FastAPI serves the frontend (static/) and the JSON endpoints.

Data modes:
  demo — built-in synthetic points (no FIRMS key);
  live — real NASA FIRMS detections when FIRMS_MAP_KEY is set.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import economics as eco
from .firms import FlareCache, cluster_persistent, fetch_detections

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("jalyn")

ROOT = Path(__file__).resolve().parent
STATIC = ROOT.parent / "static"
DB_PATH = Path(os.getenv("JALYN_DB", ROOT.parent / "jalyn.db"))
FIRMS_MAP_KEY = os.getenv("FIRMS_MAP_KEY", "").strip()

TECHNOLOGIES = json.loads((ROOT / "technologies.json").read_text(encoding="utf-8"))
DEMO = json.loads((ROOT / "demo_sites.json").read_text(encoding="utf-8"))

app = FastAPI(title="JALYN API", version="0.1.0",
              description="Flares from space → gas volume → tenge → utilization technology")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

cache = FlareCache()


# --- Database (monitoring subscriptions) ----------------------------------------
SCHEMA = """CREATE TABLE IF NOT EXISTS subscriptions (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               site_id TEXT NOT NULL,
               site_name TEXT,
               company TEXT NOT NULL,
               email TEXT NOT NULL,
               plan_kzt_per_month INTEGER NOT NULL DEFAULT 250000,
               created_at TEXT NOT NULL
           )"""


def db() -> sqlite3.Connection:
    """Open the database; the schema is applied on every connection, so a fresh or
    recreated database file (e.g. after a redeploy on an ephemeral disk) just works."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    return conn


# --- Flare data -------------------------------------------------------------------
def enrich(site: dict, nights_total: int) -> dict:
    persistence = site.get("persistence") or round(site["nights_detected"] / nights_total, 2)
    econ = eco.economics_from_frp(site["frp_mean_mw"], persistence)
    return {
        **site,
        "nights_total": nights_total,
        "persistence": persistence,
        "economics": econ.to_dict(),
    }


def demo_sites() -> list[dict]:
    n = DEMO["nights_total"]
    return [enrich({**s, "source": "DEMO DATA (synthetic)"}, n) for s in DEMO["sites"]]


def live_sites(days: int) -> list[dict]:
    cached = cache.get(days)
    if cached is None:
        detections = fetch_detections(FIRMS_MAP_KEY, days=days)
        cached = cluster_persistent(detections, days=days)
        cache.put(days, cached)
    return [enrich(s, days) for s in cached]


def get_sites(mode: str, days: int) -> tuple[str, list[dict]]:
    if mode == "demo" or (mode == "auto" and not FIRMS_MAP_KEY):
        return "demo", demo_sites()
    if not FIRMS_MAP_KEY:
        raise HTTPException(503, "FIRMS_MAP_KEY is not set — live mode is unavailable. Use mode=demo.")
    sites = live_sites(days)
    if not sites and mode == "auto":
        return "demo", demo_sites()
    return "live", sites


def find_site(site_id: str) -> dict:
    for mode in ("demo", "live") if FIRMS_MAP_KEY else ("demo",):
        try:
            _, sites = get_sites(mode, 60)
        except HTTPException:
            continue
        for s in sites:
            if s["id"] == site_id:
                return s
    raise HTTPException(404, f"Site {site_id} not found")


# --- API --------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"ok": True, "live_available": bool(FIRMS_MAP_KEY), "time": datetime.now(timezone.utc).isoformat()}


@app.get("/api/flares")
def flares(mode: str = Query("auto", pattern="^(auto|demo|live)$"), days: int = Query(60, ge=10, le=120)):
    used_mode, sites = get_sites(mode, days)
    totals = {
        "sites": len(sites),
        "gas_m3_per_year": sum(s["economics"]["gas_m3_per_year"] for s in sites),
        "methanol_value_kzt": sum(s["economics"]["methanol_value_kzt"] for s in sites),
        "electricity_value_kzt": sum(s["economics"]["electricity_value_kzt"] for s in sites),
        "co2e_t_per_year": sum(s["economics"]["co2e_t_per_year"] for s in sites),
    }
    return {
        "mode": used_mode,
        "days": days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": "VIIRS night detections → 0.015° grid → persistence ≥35% of nights → FRP → gas volume",
        "assumptions": eco.ASSUMPTIONS,
        "totals": totals,
        "sites": sites,
    }


@app.get("/api/technologies")
def technologies():
    return TECHNOLOGIES


@app.get("/api/sites/{site_id}/economics")
def site_economics(site_id: str):
    site = find_site(site_id)
    return {
        "site": site,
        "technologies": eco.match_technologies(site["economics"]["gas_m3_per_year"], TECHNOLOGIES),
        "assumptions": eco.ASSUMPTIONS,
    }


class SubscriptionIn(BaseModel):
    site_id: str
    company: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=120)
    plan_kzt_per_month: int = 250_000


@app.post("/api/subscriptions", status_code=201)
def create_subscription(sub: SubscriptionIn):
    site = find_site(sub.site_id)
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO subscriptions (site_id, site_name, company, email, plan_kzt_per_month, created_at) VALUES (?,?,?,?,?,?)",
            (sub.site_id, site["name"], sub.company, sub.email, sub.plan_kzt_per_month,
             datetime.now(timezone.utc).isoformat()),
        )
        sub_id = cur.lastrowid
    return {"id": sub_id, "site": site["name"], "company": sub.company, "plan_kzt_per_month": sub.plan_kzt_per_month,
            "status": "active", "next_report": "quarterly"}


@app.get("/api/subscriptions")
def list_subscriptions():
    with db() as conn:
        rows = conn.execute("SELECT * FROM subscriptions ORDER BY id DESC LIMIT 100").fetchall()
    return [dict(r) for r in rows]


def fmt(n: float) -> str:
    return f"{n:,.0f}"


@app.get("/api/sites/{site_id}/report", response_class=HTMLResponse)
def site_report(site_id: str):
    """Draft associated-gas utilization program for a site (print → PDF)."""
    site = find_site(site_id)
    e = site["economics"]
    techs = eco.match_technologies(e["gas_m3_per_year"], TECHNOLOGIES)
    fit = [t for t in techs if t["fit"]]
    rows = "".join(
        f"<tr><td>{t['name']}</td><td>{'fits' if t['fit'] else 'out of range'}</td>"
        f"<td>{fmt(t['capex_kzt'])}</td><td>{fmt(t['net_kzt_per_year'])}</td>"
        f"<td>{t['payback_years'] if t['payback_years'] else '—'}</td></tr>" for t in techs
    )
    rec = fit[0]["name"] if fit else "volume needs confirmation first"
    today = datetime.now().strftime("%d %b %Y")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>JALYN — utilization program · {site['name']}</title>
<style>
 body{{font-family:Inter,Arial,sans-serif;max-width:860px;margin:40px auto;color:#111;line-height:1.45;padding:0 20px}}
 h1{{font-size:26px;margin:0 0 4px}} h2{{font-size:17px;margin:28px 0 8px;border-bottom:2px solid #f26b1d;padding-bottom:4px}}
 .muted{{color:#666;font-size:13px}} table{{width:100%;border-collapse:collapse;font-size:14px}}
 td,th{{border:1px solid #ddd;padding:7px 9px;text-align:left}} th{{background:#faf3ee}}
 .kpi{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:14px 0}}
 .kpi div{{border:1px solid #eee;border-radius:10px;padding:10px}} .kpi b{{display:block;font-size:20px;color:#c2410c}}
 .badge{{display:inline-block;background:#fff1e6;color:#c2410c;border-radius:999px;padding:2px 10px;font-size:12px}}
 @media print{{button{{display:none}}}}
</style></head><body>
<div class="badge">JALYN · draft for review</div>
<h1>Associated Gas Utilization Program — {site['name']}</h1>
<div class="muted">{site['region']} · {site['lat']}, {site['lon']} · prepared {today} · detections: {site.get('source','')}</div>

<h2>1. What the satellite sees</h2>
<p>Over {site['nights_total']} nights of VIIRS observations a thermal anomaly was recorded on {site['nights_detected']} nights
(persistence {int(site['persistence']*100)}%). Mean radiated power {e['frp_mw']} MW, peak {site.get('frp_max_mw','—')} MW.
A multi-month anomaly fixed in one spot is the signature of a flare, not a wildfire.</p>

<h2>2. Volume and losses</h2>
<div class="kpi">
 <div><span class="muted">Gas, m³ / year</span><b>{fmt(e['gas_m3_per_year'])}</b></div>
 <div><span class="muted">Methanol, t / year</span><b>{fmt(e['methanol_t_per_year'])}</b></div>
 <div><span class="muted">Potential, ₸ / year (methanol)</span><b>{fmt(e['methanol_value_kzt'])}</b></div>
 <div><span class="muted">CO₂-eq, t / year</span><b>{fmt(e['co2e_t_per_year'])}</b></div>
</div>
<p class="muted">Method: thermal power = FRP ÷ {eco.RADIANT_FRACTION}; flow = thermal power ÷ {eco.GAS_LHV_MJ_PER_M3} MJ/m³;
CO₂-eq {eco.ASSUMPTIONS['co2e_kg_per_m3']} kg/m³ (World Bank GGFR 2026). Screening estimate — to be calibrated against the operator's flow meter.</p>

<h2>3. Utilization options</h2>
<table><tr><th>Technology</th><th>Volume fit</th><th>CAPEX, ₸</th><th>Net income, ₸ / year</th><th>Payback, years</th></tr>{rows}</table>
<p><b>First-pass recommendation:</b> {rec}.</p>

<h2>4. Next steps</h2>
<ol><li>Confirm the volume with an on-site measurement (1–2 weeks).</li>
<li>Request quotes from 2–3 vendors of the selected technology.</li>
<li>Add the measure to the gas-utilization program and the Zero Routine Flaring 2030 schedule.</li></ol>
<p class="muted">All prices and CAPEX are JALYN screening assumptions and must be refined. Generated automatically.</p>
<button onclick="window.print()">Save as PDF</button>
</body></html>"""


# --- Frontend ----------------------------------------------------------------------
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
