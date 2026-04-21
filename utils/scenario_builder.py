"""
utils/scenario_builder.py

Main entry point for the Jork PV optimisation project.
Runs three scenarios and saves results for the Streamlit dashboard.

Scenarios:
  0. Baseline      – existing 6,111 buildings only (today's situation)
  1. Densification – +460 smaller buildings (~120 m²) close to existing stock
  2. Sprawl        – +460 larger buildings (~220 m²) at the periphery

For each scenario:
  1. Generate buildings (existing + new)
  2. Calculate PV potential   → solar_potential.calc_pv_potential()
  3. Calculate energy demand  → energy_demand.calc_energy_demand()
  4. Run MILP optimiser       → optimise.optimise()
  5. Calculate KPIs
  6. Save results

Run with:
  python utils/scenario_builder.py

Outputs (in data/processed/):
  scenario_baseline.gpkg
  scenario_densification.gpkg
  scenario_sprawl.gpkg
  scenario_comparison.csv

Sources:
  - Scenario methodology: Frankhauser et al. (2018), Computers Environment
    and Urban Systems. https://doi.org/10.1016/j.compenvurbsys.2017.09.011
  - Building size assumptions: IWU Gebäudetypologie Deutschland 2015
    https://www.iwu.de/forschung/energie/gebaeudetypologie/
  - Growth rate (~1.5%/yr): Statistisches Amt Hamburg und Schleswig-Holstein
"""

import sys
import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import Polygon
from shapely.ops import unary_union
from pathlib import Path

ROOT    = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "utils"))

from solar_potential import (
    load_buildings, load_pvgis,
    calc_annual_irradiation, calc_representative_cf, calc_pv_potential,
)
from energy_demand import (
    calc_representative_temperatures, calc_heating_profile,
    calc_energy_demand, calc_kpis,
)
from optimise import optimise, DAYS_PER_SEASON, SEASONS, HOURS

OUT_DIR = ROOT / "data" / "processed"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Scenario parameters
# ---------------------------------------------------------------------------

N_NEW_BUILDINGS    = 460     # ~1.5%/yr × 5 years × 6,111 buildings
N_EXISTING_SAMPLE  = 1000    # fixed pool of existing buildings (same across all scenarios)
                              # ~16% of 6,111 total — realistic PV penetration by 2030
RANDOM_SEED        = 42

# Building sizes per scenario
# Source: IWU Gebäudetypologie Deutschland 2015
DENSIFICATION_AREA_MEAN = 120.0   # m² – smaller infill buildings
DENSIFICATION_AREA_STD  = 35.0
SPRAWL_AREA_MEAN        = 220.0   # m² – larger detached houses
SPRAWL_AREA_STD         = 65.0

DENSIFICATION_RADIUS    = 150.0   # max distance from existing buildings [m]
SPRAWL_INNER_FRACTION   = 0.6     # inner fraction of bbox excluded for sprawl

# Optimiser settings
# MAX_TOTAL_KWP set very high — no grid capacity constraint.
# With ~920 buildings the economic optimum (CRF × CAPEX vs grid savings)
# naturally limits installed capacity without needing an artificial cap.
MAX_TOTAL_KWP  = 999_999.0
TOP_N          = 1000         # top-1000 existing + all 460 new = ~1460 in solver


# ---------------------------------------------------------------------------
# Building generation helpers
# ---------------------------------------------------------------------------

def _make_square(cx: float, cy: float, area: float) -> Polygon:
    h = np.sqrt(area) / 2
    return Polygon([(cx-h, cy-h), (cx+h, cy-h), (cx+h, cy+h), (cx-h, cy+h)])


def generate_new_buildings(
    existing_gdf: gpd.GeoDataFrame,
    mode: str,                    # "densification" or "sprawl"
    n: int        = N_NEW_BUILDINGS,
    seed: int     = RANDOM_SEED,
) -> gpd.GeoDataFrame:
    """
    Generate N synthetic new buildings for the given scenario.

    Densification: placed within DENSIFICATION_RADIUS of existing buildings.
                   Smaller footprint (~120 m²) → less PV, less heating demand.
    Sprawl:        placed in the outer ring of the bounding box.
                   Larger footprint (~220 m²) → more PV, more heating demand.

    Source: Frankhauser et al. (2018) – spatial growth concepts.
    """
    rng = np.random.default_rng(seed)
    gdf = existing_gdf.to_crs("EPSG:25832")
    existing_union = unary_union(gdf.geometry.buffer(5))

    if mode == "densification":
        area_mean, area_std = DENSIFICATION_AREA_MEAN, DENSIFICATION_AREA_STD
        centroids = gdf.geometry.centroid
    else:
        area_mean, area_std = SPRAWL_AREA_MEAN, SPRAWL_AREA_STD
        minx, miny, maxx, maxy = gdf.total_bounds
        dx = (maxx - minx) * 0.2; dy = (maxy - miny) * 0.2
        minx -= dx; miny -= dy; maxx += dx; maxy += dy
        cx_b = (minx + maxx) / 2; cy_b = (miny + maxy) / 2
        inner_w = (maxx - minx) * SPRAWL_INNER_FRACTION / 2
        inner_h = (maxy - miny) * SPRAWL_INNER_FRACTION / 2

    areas   = np.clip(rng.normal(area_mean, area_std, n), 30, 600)
    polys   = []
    placed  = 0
    attempts = 0
    max_att  = n * 30

    while placed < n and attempts < max_att:
        if mode == "densification":
            anchor  = centroids.iloc[rng.integers(0, len(centroids))]
            angle   = rng.uniform(0, 2 * np.pi)
            dist    = rng.uniform(20, DENSIFICATION_RADIUS)
            cx = anchor.x + dist * np.cos(angle)
            cy = anchor.y + dist * np.sin(angle)
        else:
            cx = rng.uniform(minx, maxx)
            cy = rng.uniform(miny, maxy)
            if abs(cx - cx_b) < inner_w and abs(cy - cy_b) < inner_h:
                attempts += 1
                continue

        poly = _make_square(cx, cy, areas[placed])
        if not poly.intersects(existing_union):
            polys.append(poly)
            placed += 1
        attempts += 1

    print(f"  [{mode}] Placed {placed}/{n} new buildings ({attempts} attempts)")

    return gpd.GeoDataFrame(
        {
            "geometry":         polys,
            "building":         ["yes"] * len(polys),
            "area_m2":          [p.area for p in polys],
            "est_roof_area_m2": [p.area * 1.15 for p in polys],
            "is_new":           [True] * len(polys),
        },
        crs="EPSG:25832",
    ).to_crs(existing_gdf.crs)


# ---------------------------------------------------------------------------
# KPI calculation
# ---------------------------------------------------------------------------

def compute_kpis(gdf: gpd.GeoDataFrame, scenario: str) -> dict:
    """
    Compute district-level KPIs using HOURLY DISPATCH results.

    Self-sufficiency uses demand of ALL buildings (not just selected),
    so it reflects how much of the full district is covered by PV.
    Self-consumption and surplus come from actual dispatch variables
    (p_i,t, e_i,t) — correctly capturing seasonal mismatch.

    Source: Luthander et al. (2015), Applied Energy.
    https://doi.org/10.1016/j.apenergy.2015.01.014
    """
    sel = gdf[gdf["selected"] == True].copy() if "selected" in gdf.columns else gdf.iloc[:0]
    if len(sel) == 0:
        return {"scenario": scenario}

    # Demand of ALL buildings in scenario
    total_demand_all = gdf["q_total_kwh"].sum() if "q_total_kwh" in gdf.columns else 0

    # Use hourly dispatch results if available
    if "pv_consumed_kwh_yr" in sel.columns:
        total_consumed = sel["pv_consumed_kwh_yr"].sum()
        total_exported = sel["pv_exported_kwh_yr"].sum()
        total_pv       = total_consumed + total_exported
    else:
        pv_col         = "pv_yield_opt_kwh_yr" if "pv_yield_opt_kwh_yr" in sel.columns                          else "pv_yield_kwh_yr"
        total_pv       = sel[pv_col].sum()
        total_consumed = sel[[pv_col, "q_total_kwh"]].min(axis=1).sum()                          if "q_total_kwh" in sel.columns else total_pv
        total_exported = total_pv - total_consumed

    cost_col = "total_annual_cost_eur" if "total_annual_cost_eur" in sel.columns                else "annual_cost_eur"

    return {
        "scenario":            scenario,
        "n_existing":          int((~gdf["is_new"]).sum()) if "is_new" in gdf.columns else len(gdf),
        "n_new":               int(gdf["is_new"].sum())    if "is_new" in gdf.columns else 0,
        "n_selected":          len(sel),
        "total_kwp":           round(sel["s_opt_kwp"].sum(), 1),
        "capex_m_eur":         round(sel["capex_eur"].sum() / 1e6, 3),
        "net_annual_cost_eur": round(sel[cost_col].sum(), 0),
        "total_pv_mwh":        round(total_pv / 1000, 1),
        "total_demand_mwh":    round(total_demand_all / 1000, 1),
        "pv_consumed_mwh":     round(total_consumed / 1000, 1),
        "pv_exported_mwh":     round(total_exported / 1000, 1),
        "self_sufficiency":    round(total_consumed / total_demand_all, 4)
                               if total_demand_all > 0 else 0,
        "self_consumption":    round(total_consumed / total_pv, 4)
                               if total_pv > 0 else 0,
        "co2_saved_t":         round(total_pv * 380 / 1e6, 1),
        "pv_surplus_mwh":      round(total_exported / 1000, 1),
    }


# ---------------------------------------------------------------------------
# Single scenario pipeline
# ---------------------------------------------------------------------------

def run_scenario(
    scenario_name: str,
    existing_gdf: gpd.GeoDataFrame,
    new_buildings: gpd.GeoDataFrame | None,
    irradiation: float,
    cf_df: pd.DataFrame,
    temp_df: pd.DataFrame,
    heat_profile: pd.DataFrame,
) -> tuple[gpd.GeoDataFrame, dict]:
    """
    Run the full pipeline for one scenario.
    Returns (enriched GeoDataFrame, kpi dict).
    """
    print(f"\n{'='*60}")
    print(f"  SCENARIO: {scenario_name.upper()}")
    print(f"{'='*60}")

    # 1. Combine buildings
    existing = existing_gdf.copy()
    existing["is_new"] = False

    if new_buildings is not None and len(new_buildings) > 0:
        combined = pd.concat(
            [existing, new_buildings], ignore_index=True
        )
        combined = gpd.GeoDataFrame(combined, geometry="geometry",
                                    crs=existing_gdf.crs)
    else:
        combined = existing

    print(f"  Total buildings: {len(combined):,} "
          f"(existing: {(~combined['is_new']).sum():,}, "
          f"new: {combined['is_new'].sum():,})")

    # 2. PV potential
    gdf = calc_pv_potential(combined, irradiation, cf_df)

    # 3. Energy demand
    gdf = calc_energy_demand(gdf, temp_df, heat_profile)

    # 4. Optimise
    gdf = optimise(
        gdf,
        max_total_kwp=MAX_TOTAL_KWP,
        exclude_orchards=True,
        top_n=TOP_N,
    )

    # 5. KPIs
    kpis = compute_kpis(gdf, scenario_name)

    # 6. Save (drop bulky hourly columns to keep file size manageable)
    save_cols = [c for c in gdf.columns
                 if not (c.startswith("pv_") and "_h" in c)
                 and not (c.startswith("demand_") and "_h" in c)]
    out_path = OUT_DIR / f"scenario_{scenario_name}.gpkg"
    gdf[save_cols].to_file(out_path, driver="GPKG")
    print(f"  [Saved] → {out_path.name}")

    return gdf, kpis


# ---------------------------------------------------------------------------
# Main – run all three scenarios
# ---------------------------------------------------------------------------

def run_all(top_n: int = TOP_N) -> pd.DataFrame:
    """
    Run baseline + densification + sprawl scenarios.
    Returns KPI comparison DataFrame.
    """
    global TOP_N
    TOP_N = top_n

    print("=" * 60)
    print("  JORK PV SCENARIO ANALYSIS")
    print("  Baseline · Densification · Sprawl")
    print("=" * 60)

    # Load shared base data (computed once, reused across scenarios)
    print("\n[Setup] Loading shared data …")
    all_existing = load_buildings()
    all_existing["is_new"] = False
    pvgis_df  = load_pvgis()

    irradiation  = calc_annual_irradiation(pvgis_df)
    cf_df        = calc_representative_cf(pvgis_df)
    temp_df      = calc_representative_temperatures(pvgis_df)
    heat_profile = calc_heating_profile(temp_df)

    # Select the TOP-N LARGEST existing buildings as fixed pool
    # (by footprint area — largest roofs = most PV potential)
    # Same pool used across all scenarios for fair comparison.
    existing = (
        all_existing
        .nlargest(N_EXISTING_SAMPLE, "area_m2")
        .copy()
        .reset_index(drop=True)
    )
    print(f"\n[Setup] Fixed existing pool: {len(existing):,} largest buildings "
          f"(from {len(all_existing):,} total, min area: "
          f"{existing['area_m2'].min():.0f} m²)")

    # Generate new buildings — use all_existing as spatial reference
    print("\n[Setup] Generating new buildings …")
    new_dense  = generate_new_buildings(all_existing, mode="densification")
    new_sprawl = generate_new_buildings(all_existing, mode="sprawl")

    # Run all three scenarios
    all_kpis = []

    _, kpis = run_scenario(
        "baseline", existing, None,
        irradiation, cf_df, temp_df, heat_profile,
    )
    all_kpis.append(kpis)

    _, kpis = run_scenario(
        "densification", existing, new_dense,
        irradiation, cf_df, temp_df, heat_profile,
    )
    all_kpis.append(kpis)

    _, kpis = run_scenario(
        "sprawl", existing, new_sprawl,
        irradiation, cf_df, temp_df, heat_profile,
    )
    all_kpis.append(kpis)

    # Save comparison table
    comparison = pd.DataFrame(all_kpis)
    out_path   = OUT_DIR / "scenario_comparison.csv"
    comparison.to_csv(out_path, index=False)

    # Print summary
    print(f"\n{'='*60}")
    print("  SCENARIO COMPARISON")
    print(f"{'='*60}")
    display_cols = [
        "scenario", "n_new", "n_selected", "total_kwp",
        "total_pv_mwh", "total_demand_mwh",
        "self_sufficiency", "self_consumption",
        "co2_saved_t", "net_annual_cost_eur",
    ]
    display_cols = [c for c in display_cols if c in comparison.columns]
    print(comparison[display_cols].to_string(index=False))
    print(f"\n[Saved] Comparison → {out_path.name}")

    return comparison


if __name__ == "__main__":
    comparison = run_all(top_n=TOP_N)