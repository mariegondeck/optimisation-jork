"""
utils/optimizer.py

Solves a binary optimisation problem:
  Which subset of rooftops in Jork / Altes Land should receive PV panels
  to maximise annual energy yield, subject to practical constraints?

Formulation:
  Variables:   x_i ∈ {0, 1}   for each building i
  Objective:   maximise  Σ_i  x_i · pv_yield_kwh_yr_i
  Constraints:
    (1) Total installed peak power  ≤  max_peak_power_kwp
    (2) Total number of buildings   ≥  min_buildings          (optional)
    (3) Orchards excluded           →  x_i = 0 for orchard buildings
    (4) Max investment cost         ≤  max_cost_eur           (optional)

Solver: CBC (bundled with PuLP – no separate install needed)

Sources:
  - PuLP docs:         https://coin-or.github.io/pulp/
  - CBC solver:        https://github.com/coin-or/Cbc
  - Cost assumption:   ~1000 EUR/kWp (utility-scale residential, Germany 2024)
    Bundesnetzagentur, Photovoltaik-Monitoring 2024
    https://www.bundesnetzagentur.de
"""

import geopandas as gpd
import pandas as pd
import pulp
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT      = Path(__file__).resolve().parent.parent
DATA_DIR  = ROOT / "data" / "processed"
OUT_DIR   = ROOT / "data" / "processed"

# ---------------------------------------------------------------------------
# Cost assumption
# ---------------------------------------------------------------------------

# Approximate installed cost per kWp (Germany, small rooftop, 2024)
# Source: Bundesnetzagentur Photovoltaik-Monitoring 2024
COST_PER_KWP_EUR = 1000.0


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

def load_pv_potential() -> gpd.GeoDataFrame:
    path = DATA_DIR / "pv_potential_jork.gpkg"
    if not path.exists():
        raise FileNotFoundError(
            f"PV potential file not found: {path}\n"
            "Run solar_potential.py first."
        )
    gdf = gpd.read_file(path)
    print(f"[Optimizer] Loaded {len(gdf)} buildings with PV potential")
    return gdf


# ---------------------------------------------------------------------------
# Core optimisation function
# ---------------------------------------------------------------------------

def optimise(
    gdf: gpd.GeoDataFrame,
    max_peak_power_kwp: float = 5000.0,   # constraint (1): max total kWp
    min_buildings: int        = 10,        # constraint (2): min buildings selected
    exclude_orchards: bool    = True,      # constraint (3): no orchard roofs
    max_cost_eur: float       = None,      # constraint (4): optional budget cap
    cost_per_kwp: float       = COST_PER_KWP_EUR,
) -> gpd.GeoDataFrame:
    """
    Run the binary integer programme and return the input GeoDataFrame
    enriched with a boolean column `selected` indicating which buildings
    were chosen by the solver.

    Parameters
    ----------
    gdf                : GeoDataFrame from solar_potential.py
    max_peak_power_kwp : maximum total installed capacity [kWp]
    min_buildings      : minimum number of buildings that must be selected
    exclude_orchards   : if True, buildings on orchard land are forced to 0
    max_cost_eur       : optional maximum total investment cost [EUR]
    cost_per_kwp       : installation cost per kWp [EUR/kWp]

    Returns
    -------
    GeoDataFrame with added columns:
        selected        : bool  – chosen by optimizer
        cost_eur        : float – estimated installation cost per building
        pv_yield_kwh_yr : already present, repeated here for clarity
    """
    gdf = gdf.copy()
    gdf["cost_eur"] = gdf["peak_power_kwp"] * cost_per_kwp

    n = len(gdf)
    indices = list(range(n))

    # -------------------------------------------------------------------
    # Build PuLP model
    # -------------------------------------------------------------------
    model = pulp.LpProblem("JorkPV_RoofOptimiser", pulp.LpMaximize)

    # Binary decision variables: x[i] = 1 → install PV on building i
    x = [pulp.LpVariable(f"x_{i}", cat="Binary") for i in indices]

    # Objective: maximise total annual PV yield
    model += pulp.lpSum(
        x[i] * gdf.iloc[i]["pv_yield_kwh_yr"] for i in indices
    ), "Total_PV_Yield"

    # Constraint (1): total peak power cap
    model += (
        pulp.lpSum(x[i] * gdf.iloc[i]["peak_power_kwp"] for i in indices)
        <= max_peak_power_kwp,
        "Max_Peak_Power"
    )

    # Constraint (2): minimum number of buildings
    model += (
        pulp.lpSum(x[i] for i in indices) >= min_buildings,
        "Min_Buildings"
    )

    # Constraint (3): exclude orchard buildings (No Net Land Take principle)
    if exclude_orchards and "building" in gdf.columns:
        orchard_mask = gdf["building"].str.lower().isin(
            ["farm", "barn", "greenhouse", "stable"]
        )
        # Note: OSM doesn't tag buildings as "orchard" – we proxy by building
        # types typically found on orchard land in the Altes Land region.
        # A more precise approach would spatially join buildings with the
        # orchard landuse polygons from fetch_gis_data.py → fetch_landuse().
        orchard_idx = gdf[orchard_mask].index.tolist()
        for i, idx in enumerate(gdf.index):
            if idx in orchard_idx:
                model += (x[i] == 0, f"ExcludeOrchard_{i}")
        print(f"[Optimizer] Excluded {len(orchard_idx)} orchard-type buildings")

    # Constraint (4): optional investment budget cap
    if max_cost_eur is not None:
        model += (
            pulp.lpSum(x[i] * gdf.iloc[i]["cost_eur"] for i in indices)
            <= max_cost_eur,
            "Max_Investment_Cost"
        )
        print(f"[Optimizer] Budget cap: {max_cost_eur:,.0f} EUR")

    # -------------------------------------------------------------------
    # Solve
    # -------------------------------------------------------------------
    print(f"\n[Optimizer] Solving with CBC …")
    solver = pulp.PULP_CBC_CMD(msg=False)   # msg=False → suppress CBC log
    status = model.solve(solver)

    print(f"[Optimizer] Status:  {pulp.LpStatus[model.status]}")
    print(f"[Optimizer] Solver:  CBC (bundled with PuLP)")

    if pulp.LpStatus[model.status] != "Optimal":
        raise RuntimeError(
            f"Solver did not find an optimal solution. Status: "
            f"{pulp.LpStatus[model.status]}\n"
            "Try relaxing the constraints (e.g. lower min_buildings "
            "or raise max_peak_power_kwp)."
        )

    # -------------------------------------------------------------------
    # Extract results
    # -------------------------------------------------------------------
    selected = [bool(pulp.value(x[i])) for i in indices]
    gdf["selected"] = selected

    # -------------------------------------------------------------------
    # Print summary
    # -------------------------------------------------------------------
    sel = gdf[gdf["selected"]]
    total_yield  = sel["pv_yield_kwh_yr"].sum()
    total_power  = sel["peak_power_kwp"].sum()
    total_cost   = sel["cost_eur"].sum()

    print(f"\n{'='*50}")
    print(f"  OPTIMISATION RESULTS")
    print(f"{'='*50}")
    print(f"  Buildings selected:   {len(sel):,}  /  {n:,}")
    print(f"  Total peak power:     {total_power:,.1f} kWp")
    print(f"  Total annual yield:   {total_yield/1e3:,.1f} MWh/yr")
    print(f"  Est. investment:      {total_cost/1e6:.2f} M EUR")
    print(f"  Objective value:      {pulp.value(model.objective):,.1f} kWh/yr")
    print(f"{'='*50}\n")

    return gdf


# ---------------------------------------------------------------------------
# Save results
# ---------------------------------------------------------------------------

def save_results(gdf: gpd.GeoDataFrame) -> Path:
    out_path = OUT_DIR / "optimisation_results_jork.gpkg"
    gdf.to_file(out_path, driver="GPKG")
    print(f"[Saved] Optimisation results → {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    max_peak_power_kwp: float = 5000.0,
    min_buildings: int        = 10,
    exclude_orchards: bool    = True,
    max_cost_eur: float       = None,
) -> gpd.GeoDataFrame:
    """
    Full pipeline: load → optimise → save.
    Returns enriched GeoDataFrame with `selected` column.
    """
    gdf = load_pv_potential()
    gdf = optimise(
        gdf,
        max_peak_power_kwp=max_peak_power_kwp,
        min_buildings=min_buildings,
        exclude_orchards=exclude_orchards,
        max_cost_eur=max_cost_eur,
    )
    save_results(gdf)
    return gdf


if __name__ == "__main__":
    print("=== PV Roof Optimiser – Jork / Altes Land ===\n")

    # Example run: max 5 MW installed, at least 10 buildings, no orchards
    gdf = run(
        max_peak_power_kwp=5000,
        min_buildings=10,
        exclude_orchards=True,
        max_cost_eur=None,       # no budget cap
    )

    print("Selected buildings:")
    print(
        gdf[gdf["selected"]][
            ["building", "area_m2", "peak_power_kwp", "pv_yield_kwh_yr", "cost_eur"]
        ].sort_values("pv_yield_kwh_yr", ascending=False).head(10)
    )