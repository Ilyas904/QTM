"""
JALYN — flare economics.

Every coefficient below is an explicit assumption kept in one place so that the jury
(and we) can check and change it. Units: gas in standard m³, money in tenge (₸),
energy in MJ / kWh.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

# --- Flare physics -------------------------------------------------------------
# Lower heating value of associated gas, MJ/m³ (34–40 depending on composition).
GAS_LHV_MJ_PER_M3 = 36.0
# Share of heat released as radiation (radiant fraction of a gas flare ≈ 0.2–0.3).
# The satellite measures radiation (FRP, MW), so we divide FRP by this share.
RADIANT_FRACTION = 0.25
SECONDS_PER_YEAR = 365 * 24 * 3600

# --- Greenhouse gases ---------------------------------------------------------
# World Bank, Global Gas Flaring Tracker 2026: 167 bcm flared in 2025 → 429 Mt CO₂-eq
# (including ~50 Mt from unburned methane). 429e9 kg / 167e9 m³ ≈ 2.57 kg/m³.
CO2E_KG_PER_M3 = 429e9 / 167e9

# --- Prices (assumptions, labelled "our assumption" on the slides) -----------
METHANOL_M3_PER_T = 1100.0          # m³ of gas per tonne of methanol (feedstock + fuel)
METHANOL_PRICE_KZT_PER_T = 250_000  # import parity, benchmark
ELECTRICITY_KWH_PER_M3 = 3.5        # gas engine at ~35% efficiency (36 MJ = 10 kWh of heat)
ELECTRICITY_PRICE_KZT_PER_KWH = 25  # industrial tariff, benchmark
KZT_PER_USD = 480                   # to convert CAPEX benchmarks


@dataclass
class FlareEconomics:
    frp_mw: float
    gas_m3_per_day: float
    gas_m3_per_year: float
    methanol_t_per_year: float
    methanol_value_kzt: float
    electricity_mwh_per_year: float
    electricity_value_kzt: float
    co2e_t_per_year: float

    def to_dict(self) -> dict:
        return asdict(self)


def frp_to_gas_flow_m3_per_s(frp_mw: float) -> float:
    """FRP (MW of radiation) → gas flow, m³/s.

    thermal_MW = FRP / RADIANT_FRACTION ; m³/s = thermal_MW (MJ/s) / LHV (MJ/m³)
    """
    if frp_mw <= 0:
        return 0.0
    thermal_mw = frp_mw / RADIANT_FRACTION
    return thermal_mw / GAS_LHV_MJ_PER_M3


def economics_from_frp(frp_mw: float, persistence: float = 1.0) -> FlareEconomics:
    """Flare economics from the mean night-time FRP.

    persistence — share of nights the flare is visible (0..1). If it does not burn every
    night the annual volume is proportionally smaller. Clouds push the estimate down —
    deliberately conservative.
    """
    flow = frp_to_gas_flow_m3_per_s(frp_mw) * max(0.0, min(1.0, persistence))
    per_year = flow * SECONDS_PER_YEAR
    methanol_t = per_year / METHANOL_M3_PER_T
    elec_mwh = per_year * ELECTRICITY_KWH_PER_M3 / 1000.0
    return FlareEconomics(
        frp_mw=round(frp_mw, 2),
        gas_m3_per_day=round(flow * 86400),
        gas_m3_per_year=round(per_year),
        methanol_t_per_year=round(methanol_t, 1),
        methanol_value_kzt=round(methanol_t * METHANOL_PRICE_KZT_PER_T),
        electricity_mwh_per_year=round(elec_mwh),
        electricity_value_kzt=round(elec_mwh * 1000 * ELECTRICITY_PRICE_KZT_PER_KWH),
        co2e_t_per_year=round(per_year * CO2E_KG_PER_M3 / 1000),
    )


def match_technologies(gas_m3_per_year: float, technologies: list[dict]) -> list[dict]:
    """Match utilization technologies to the gas volume and compute payback.

    Each catalog entry carries (assumptions) a volume range, CAPEX per 1 m³/year of
    capacity, OPEX and revenue per m³. Payback = CAPEX / (revenue − OPEX).
    Technologies outside the range are returned too, flagged fit=False, so the UI can
    show why they do not apply.
    """
    results = []
    for tech in technologies:
        fits = tech["min_m3_per_year"] <= gas_m3_per_year <= tech["max_m3_per_year"]
        capex = gas_m3_per_year * tech["capex_kzt_per_m3_year"]
        revenue = gas_m3_per_year * tech["revenue_kzt_per_m3"]
        opex = gas_m3_per_year * tech["opex_kzt_per_m3"]
        net = revenue - opex
        payback_years = round(capex / net, 1) if net > 0 else None
        results.append(
            {
                **tech,
                "fit": fits,
                "capex_kzt": round(capex),
                "revenue_kzt_per_year": round(revenue),
                "opex_kzt_per_year": round(opex),
                "net_kzt_per_year": round(net),
                "payback_years": payback_years,
            }
        )
    # Fitting technologies first, then by payback
    results.sort(key=lambda t: (not t["fit"], t["payback_years"] if t["payback_years"] else 1e9))
    return results


ASSUMPTIONS = {
    "gas_lhv_mj_per_m3": GAS_LHV_MJ_PER_M3,
    "radiant_fraction": RADIANT_FRACTION,
    "co2e_kg_per_m3": round(CO2E_KG_PER_M3, 2),
    "methanol_m3_per_t": METHANOL_M3_PER_T,
    "methanol_price_kzt_per_t": METHANOL_PRICE_KZT_PER_T,
    "electricity_kwh_per_m3": ELECTRICITY_KWH_PER_M3,
    "electricity_price_kzt_per_kwh": ELECTRICITY_PRICE_KZT_PER_KWH,
    "kzt_per_usd": KZT_PER_USD,
    "note": "All coefficients are screening assumptions; they are calibrated against the operator's flow meters.",
}
