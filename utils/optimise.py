"""
utils/optimise.py

MILP core for PV rooftop investment optimisation with hourly dispatch.
This module is a library — it is called by scenario_builder.py.
Do not run this file directly.

=============================================================================
PROBLEM FORMULATION
=============================================================================

Decision variables:
  x_i   ∈ {0,1}         binary: install PV on building i or not
  s_i   ∈ [0, s_max_i]  continuous: installed PV capacity [kWp]
  g_i,t ≥ 0             grid import [kWh] for building i in hour t
  e_i,t ≥ 0             grid export / feed-in [kWh] for building i in hour t
  p_i,t ≥ 0             local PV consumption [kWh] for building i in hour t

Objective (minimise total annual costs):
  min  Σ_i [ x_i · CAPEX_fix  +  s_i · CAPEX_kwp ]
     + Σ_i Σ_season Σ_h  w · [ g_i,t · c_grid  −  e_i,t · c_feedin ]

  w = DAYS_PER_SEASON ≈ 91.25  (scales one representative day to full season)

Constraints:
  (1)  p_i,t + g_i,t = demand_i,t        ∀i,t   energy balance
  (2)  p_i,t + e_i,t ≤ s_i · CF_t        ∀i,t   PV output limit
  (3)  s_i ≤ s_max_i · x_i               ∀i     capacity only if installed
  (4)  s_i ≥ s_min · x_i                 ∀i     minimum viable system
  (5)  Σ_i s_i ≤ max_total_kwp                   grid capacity constraint
  (6)  x_i = 0 for orchard buildings             No Net Land Take

Sources:
  - MILP formulation: inspired by MANGO (Mavromatidis & Petkov, 2021)
    Applied Energy 288. https://doi.org/10.1016/j.apenergy.2021.116585
  - Grid price (Germany 2024): Bundesnetzagentur Monitoringbericht 2024
  - Feed-in tariff (EEG 2024, ≤10 kWp): bundesnetzagentur.de/eeg
  - PV cost: Bundesnetzagentur PV-Monitoring 2024
  - Solver: CBC via PuLP. https://coin-or.github.io/pulp/
"""

import geopandas as gpd
import pandas as pd
import numpy as np
import pulp

# ---------------------------------------------------------------------------
# Economic parameters
# ---------------------------------------------------------------------------
CAPEX_FIX_EUR    = 500.0    # fixed cost per installation [€]
CAPEX_KWP_EUR    = 1000.0   # variable cost per kWp [€/kWp]
C_GRID_EUR_KWH   = 0.29     # grid import price [€/kWh], Bundesnetzagentur 2024
C_FEEDIN_EUR_KWH = 0.01     # conservative Direktvermarktung spot price [€/kWh]
# Rationale: With true Nulleinspeisung (c_feedin=0), the optimizer installs
# exactly as much PV as can be consumed locally → zero summer surplus by design.
# A small value (1 ct/kWh) reflects conservative Direktvermarktung at spot prices
# (~3-8 ct/kWh realistically, modelled conservatively here at 1 ct/kWh).
# This incentivises slightly larger installations that naturally create summer
# surplus while still strongly favouring self-consumption over export.
# Source: Finanztip (2026), Bundeswirtschaftsministerium EEG-Novelle
# https://www.finanztip.de/photovoltaik/einspeiseverguetung/
S_MIN_KWP        = 1.0      # minimum viable system size [kWp]

# Capital Recovery Factor — annualises CAPEX so all costs are in €/yr
# CRF = r(1+r)^n / ((1+r)^n - 1)
# Method: standard in ESM, follows MANGO (Mavromatidis & Petkov, 2021)
DISCOUNT_RATE   = 0.05     # 5% — typical residential PV in Germany
SYSTEM_LIFETIME = 20       # years — standard PV panel lifetime
CRF = (DISCOUNT_RATE * (1 + DISCOUNT_RATE) ** SYSTEM_LIFETIME) / \
      ((1 + DISCOUNT_RATE) ** SYSTEM_LIFETIME - 1)
# CRF ≈ 0.0802 → 1,000 € CAPEX becomes ~80 €/yr annualised

SEASONS         = ["winter", "spring", "summer", "autumn"]
HOURS           = list(range(24))
DAYS_PER_SEASON = 365.0 / 4


# ---------------------------------------------------------------------------
# Core optimisation function  (called by scenario_builder.py)
# ---------------------------------------------------------------------------

def optimise(
    gdf: gpd.GeoDataFrame,
    max_total_kwp: float   = 5000.0,
    exclude_orchards: bool = True,
    capex_fix: float       = CAPEX_FIX_EUR,
    capex_kwp: float       = CAPEX_KWP_EUR,
    c_grid: float          = C_GRID_EUR_KWH,
    c_feedin: float        = C_FEEDIN_EUR_KWH,
    s_min: float           = S_MIN_KWP,
    top_n: int             = 200,
    solver_msg: bool       = False,
) -> gpd.GeoDataFrame:
    """
    Run the MILP and return GeoDataFrame enriched with result columns:
      selected            bool   – building chosen
      s_opt_kwp           float  – optimal installed capacity [kWp]
      capex_eur           float  – investment cost [€]
      annual_cost_eur     float  – net annual cost (grid - feedin) [€/yr]
      pv_yield_opt_kwh_yr float  – annual yield at optimal capacity [kWh/yr]

    Parameters
    ----------
    gdf    : merged GeoDataFrame with pv_* and demand_* hourly columns
    top_n  : pre-filter to top-N buildings by PV yield (solver speed)
    """
    # ------------------------------------------------------------------
    # Initialise result columns on full GeoDataFrame
    # ------------------------------------------------------------------
    gdf_full = gdf.copy()
    for col, val in [("selected", False), ("s_opt_kwp", 0.0),
                     ("capex_eur", 0.0), ("capex_annualised_eur", 0.0),
                     ("annual_cost_eur", 0.0), ("total_annual_cost_eur", 0.0),
                     ("pv_yield_opt_kwh_yr", 0.0),
                     ("grid_import_kwh_yr", 0.0),
                     ("pv_consumed_kwh_yr", 0.0),
                     ("pv_exported_kwh_yr", 0.0)]:
        gdf_full[col] = val

    # ------------------------------------------------------------------
    # Pre-filter to top-N by PV yield
    # ------------------------------------------------------------------
    if "pv_yield_kwh_yr" not in gdf_full.columns:
        raise ValueError("Missing 'pv_yield_kwh_yr'. Run solar_potential.py first.")

    # Pre-filter: top-N from existing buildings + ALL new buildings
    # This ensures new buildings always enter the solver regardless of size.
    # Add original index before filtering so we can merge back later
    gdf_full["_orig_idx"] = gdf_full.index

    if "is_new" in gdf_full.columns:
        new_bldgs      = gdf_full[gdf_full["is_new"] == True]
        existing_bldgs = gdf_full[gdf_full["is_new"] == False]
        # Take top-N from existing AND top-N from new buildings separately
        # so both groups are equally represented regardless of size
        top_existing = existing_bldgs.nlargest(top_n, "pv_yield_kwh_yr")
        top_new      = new_bldgs.nlargest(top_n, "pv_yield_kwh_yr")                        if len(new_bldgs) > 0 else new_bldgs
        sub = pd.concat([top_existing, top_new], ignore_index=True)
    else:
        sub = gdf_full.nlargest(top_n, "pv_yield_kwh_yr")
    sub = sub.reset_index(drop=True)
    n   = len(sub)
    print(f"  [MILP] Solving over {n} buildings (pre-filtered from {len(gdf_full):,})")

    # ------------------------------------------------------------------
    # Orchard exclusion
    # ------------------------------------------------------------------
    orchard_mask = pd.Series(False, index=sub.index)
    if exclude_orchards and "building" in sub.columns:
        orchard_types = {"farm", "barn", "greenhouse", "stable"}
        orchard_mask  = sub["building"].str.lower().isin(orchard_types)

    # ------------------------------------------------------------------
    # Check hourly columns
    # ------------------------------------------------------------------
    has_hourly = all(
        f"demand_{s}_h{h:02d}" in sub.columns and f"pv_{s}_h{h:02d}" in sub.columns
        for s in SEASONS for h in HOURS
    )
    if not has_hourly:
        raise ValueError(
            "Missing hourly columns. Run solar_potential.py and energy_demand.py first."
        )

    # ------------------------------------------------------------------
    # Build model
    # ------------------------------------------------------------------
    model = pulp.LpProblem("JorkPV_HourlyDispatch", pulp.LpMinimize)

    x = [pulp.LpVariable(f"x_{i}", cat="Binary") for i in range(n)]
    s = [pulp.LpVariable(f"s_{i}", lowBound=0,
                         upBound=float(sub.iloc[i]["peak_power_kwp"]))
         for i in range(n)]

    g, e, p = {}, {}, {}
    for i in range(n):
        g[i], e[i], p[i] = {}, {}, {}
        for season in SEASONS:
            g[i][season], e[i][season], p[i][season] = {}, {}, {}
            for h in HOURS:
                tag = f"{i}_{season}_{h}"
                g[i][season][h] = pulp.LpVariable(f"g_{tag}", lowBound=0)
                e[i][season][h] = pulp.LpVariable(f"e_{tag}", lowBound=0)
                p[i][season][h] = pulp.LpVariable(f"p_{tag}", lowBound=0)

    # Objective: minimise ANNUALISED CAPEX + annual grid costs
    # CAPEX × CRF converts one-off investment to equivalent annual cost [€/yr]
    # so all terms are in €/yr and directly comparable.
    # Method: MANGO (Mavromatidis & Petkov, 2021), Applied Energy 288
    model += (
        pulp.lpSum(CRF * (capex_fix * x[i] + capex_kwp * s[i]) for i in range(n))
        + pulp.lpSum(
            DAYS_PER_SEASON * (c_grid * g[i][season][h] - c_feedin * e[i][season][h])
            for i in range(n) for season in SEASONS for h in HOURS
        ),
        "Total_Annual_Cost_EUR_per_yr"
    )

    # Constraints
    for i in range(n):
        row    = sub.iloc[i]
        s_max  = float(row["peak_power_kwp"])

        model += (s[i] <= s_max  * x[i], f"cap_max_{i}")
        model += (s[i] >= s_min  * x[i], f"cap_min_{i}")

        if orchard_mask.iloc[i]:
            model += (x[i] == 0, f"orchard_{i}")

        for season in SEASONS:
            for h in HOURS:
                d  = float(row.get(f"demand_{season}_h{h:02d}", 0))
                cf = float(row.get(f"pv_{season}_h{h:02d}", 0))

                model += (p[i][season][h] + g[i][season][h] == d,
                          f"bal_{i}_{season}_{h}")
                model += (p[i][season][h] + e[i][season][h] <= s[i] * cf,
                          f"pv_{i}_{season}_{h}")

    model += (pulp.lpSum(s[i] for i in range(n)) <= max_total_kwp, "kwp_limit")

    # ------------------------------------------------------------------
    # Solve
    # ------------------------------------------------------------------
    print(f"  [MILP] {len(model.variables()):,} variables · "
          f"{len(model.constraints):,} constraints")
    solver = pulp.PULP_CBC_CMD(msg=solver_msg)
    model.solve(solver)

    status = pulp.LpStatus[model.status]
    print(f"  [MILP] Status: {status}")
    if status != "Optimal":
        raise RuntimeError(f"No optimal solution: {status}")

    # ------------------------------------------------------------------
    # Extract results into sub
    # ------------------------------------------------------------------
    sub["selected"]  = [bool(round(pulp.value(x[i]) or 0)) for i in range(n)]
    sub["s_opt_kwp"] = [max(pulp.value(s[i]) or 0, 0)      for i in range(n)]
    sub["capex_eur"] = [
        (capex_fix + capex_kwp * sub.iloc[i]["s_opt_kwp"]) * sub.iloc[i]["selected"]
        for i in range(n)
    ]
    sub["capex_annualised_eur"] = [
        CRF * (capex_fix + capex_kwp * sub.iloc[i]["s_opt_kwp"]) * sub.iloc[i]["selected"]
        for i in range(n)
    ]

    # ------------------------------------------------------------------
    # Aggregate hourly dispatch → annual totals per building
    # This is the correct way to compute self-sufficiency/self-consumption:
    # from actual dispatch results, not from annual yield approximations.
    # ------------------------------------------------------------------
    sub["grid_import_kwh_yr"] = [
        DAYS_PER_SEASON * sum(
            (pulp.value(g[i][se][h]) or 0)
            for se in SEASONS for h in HOURS
        )
        for i in range(n)
    ]
    sub["pv_consumed_kwh_yr"] = [
        DAYS_PER_SEASON * sum(
            (pulp.value(p[i][se][h]) or 0)
            for se in SEASONS for h in HOURS
        )
        for i in range(n)
    ]
    sub["pv_exported_kwh_yr"] = [
        DAYS_PER_SEASON * sum(
            (pulp.value(e[i][se][h]) or 0)
            for se in SEASONS for h in HOURS
        )
        for i in range(n)
    ]

    sub["annual_cost_eur"] = (
        sub["grid_import_kwh_yr"] * c_grid
      - sub["pv_exported_kwh_yr"] * c_feedin
    )
    sub["total_annual_cost_eur"] = sub["capex_annualised_eur"] + sub["annual_cost_eur"]
    sub["pv_yield_opt_kwh_yr"]   = sub["pv_consumed_kwh_yr"] + sub["pv_exported_kwh_yr"]

    # ------------------------------------------------------------------
    # Merge back into full GeoDataFrame
    # New buildings have no osmid so we use a positional index approach:
    # sub was built from gdf_full rows → track original index via helper col
    # ------------------------------------------------------------------
    result_cols = ["selected", "s_opt_kwp", "capex_eur", "capex_annualised_eur",
                   "annual_cost_eur", "total_annual_cost_eur", "pv_yield_opt_kwh_yr",
                   "grid_import_kwh_yr", "pv_consumed_kwh_yr", "pv_exported_kwh_yr"]

    # Store original gdf_full index in sub before reset_index was called
    # We rebuild by adding a temp _orig_idx column before pre-filter
    # Fallback: use positional merge via _sub_orig_idx stored earlier
    if "_orig_idx" in sub.columns:
        for col in result_cols:
            gdf_full.loc[sub["_orig_idx"], col] = sub[col].values
    elif "osmid" in gdf_full.columns and "osmid" in sub.columns:
        # Only use osmid merge when osmid is unique and non-null
        sub_clean = sub.dropna(subset=["osmid"])
        sub_clean = sub_clean[~sub_clean["osmid"].duplicated(keep="first")]
        sub_idx   = sub_clean.set_index("osmid")
        mask = gdf_full["osmid"].isin(sub_idx.index) & gdf_full["osmid"].notna()
        for col in result_cols:
            gdf_full.loc[mask, col] = (
                gdf_full.loc[mask, "osmid"].map(sub_idx[col])
            )
        # New buildings (no osmid) – merge positionally via sub index
        no_osmid_sub  = sub[sub["osmid"].isna() | (sub["osmid"] == "")]
        no_osmid_full = gdf_full[gdf_full["osmid"].isna() | (gdf_full["osmid"] == "")]
        if len(no_osmid_sub) > 0 and len(no_osmid_full) > 0:
            n_match = min(len(no_osmid_sub), len(no_osmid_full))
            for col in result_cols:
                gdf_full.loc[
                    no_osmid_full.index[:n_match], col
                ] = no_osmid_sub[col].values[:n_match]
    else:
        for col in result_cols:
            gdf_full.loc[sub.index, col] = sub[col].values

    # Clean up helper column
    gdf_full = gdf_full.drop(columns=["_orig_idx"], errors="ignore")

    # Summary
    sel = gdf_full[gdf_full["selected"] == True]
    print(f"  [MILP] Selected: {len(sel):,} buildings · "
          f"{sel['s_opt_kwp'].sum():,.1f} kWp · "
          f"CAPEX: {sel['capex_eur'].sum()/1e6:.2f} M€ · "
          f"Net annual cost: {sel['annual_cost_eur'].sum():,.0f} €/yr")

    return gdf_full