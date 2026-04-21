"""
utils/solar_potential.py

Calculates PV potential for each building in Jork / Altes Land.

Two outputs per building:
  1. Annual yield [kWh/yr]  – for map visualisation & simple KPIs
  2. Hourly capacity factors [kW/kWp] for 4 representative days
     – used by the hourly optimiser (optimise.py)

Representative days (one per season):
  Winter:  15 January   – low PV, high heating demand
  Spring:  15 April     – medium PV, Altes Land blossom season :)
  Summer:  15 July      – peak PV, low heating demand
  Autumn:  15 October   – medium PV, rising heating demand

Each representative day stands for ~91 days (365/4).
This approach is consistent with the "typical year" methodology
used in KomMod (Fraunhofer ISE) and MANGO (Mavromatidis 2021).

Sources:
  - Building footprints: OpenStreetMap, ODbL licence
  - Irradiance data:     EU JRC PVGIS SARAH-2, CC BY 4.0
                         https://re.jrc.ec.europa.eu/pvg_tools/en/
  - Panel efficiency:    Fraunhofer ISE Photovoltaics Report 2024
  - Representative day methodology:
    Mavromatidis G., Petkov I. (2021). MANGO. Applied Energy 288.
    https://doi.org/10.1016/j.apenergy.2021.116585
"""

import geopandas as gpd
import pandas as pd
import numpy as np
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT     = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "raw"
OUT_DIR  = ROOT / "data" / "processed"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# PV system parameters
# ---------------------------------------------------------------------------
USABLE_ROOF_FRACTION = 0.65   # usable share of roof area
PANEL_EFFICIENCY     = 0.20   # crystalline silicon, Fraunhofer ISE 2024
PERFORMANCE_RATIO    = 0.80   # inverter + cable losses, PVGIS default
MIN_ROOF_AREA_M2     = 20.0   # minimum roof area to be considered

# ---------------------------------------------------------------------------
# Representative days – (month, day) tuples
# Each represents ~91 days of the year (365/4)
# ---------------------------------------------------------------------------
REPRESENTATIVE_DAYS = {
    "winter": (1, 15),    # 15 January
    "spring": (4, 15),    # 15 April
    "summer": (7, 15),    # 15 July
    "autumn": (10, 15),   # 15 October
}
DAYS_PER_SEASON = 365.0 / 4   # weight for annualisation (~91.25 days)


# ---------------------------------------------------------------------------
# 1.  Load data
# ---------------------------------------------------------------------------

def load_buildings() -> gpd.GeoDataFrame:
    path = DATA_DIR / "buildings_jork.gpkg"
    if not path.exists():
        raise FileNotFoundError(f"Buildings not found: {path}\nRun fetch_gis_data.py first.")
    gdf = gpd.read_file(path)
    print(f"[Buildings] Loaded {len(gdf):,} buildings")
    return gdf


def load_pvgis(year_from: int = 2016, year_to: int = 2020) -> pd.DataFrame:
    path = DATA_DIR / f"pvgis_jork_{year_from}_{year_to}.csv"
    if not path.exists():
        raise FileNotFoundError(f"PVGIS data not found: {path}\nRun fetch_gis_data.py first.")
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True)
    print(f"[PVGIS] Loaded {len(df):,} hourly rows")
    return df


# ---------------------------------------------------------------------------
# 2.  Annual irradiation  [kWh/m²/yr]
# ---------------------------------------------------------------------------

def calc_annual_irradiation(pvgis_df: pd.DataFrame) -> float:
    """
    Mean annual in-plane irradiation from PVGIS hourly data.
    poa_total = poa_direct + poa_sky_diffuse + poa_ground_diffuse  [W/m²]
    Summed over hours → Wh/m² → /1000 → kWh/m²
    Averaged over all years in dataset.
    """
    df = pvgis_df.copy()
    df["poa_total"] = (
        df["poa_direct"] + df["poa_sky_diffuse"] + df["poa_ground_diffuse"]
    )
    n_years = df.index.year.nunique()
    annual  = df["poa_total"].sum() / 1000 / n_years
    print(f"[Irradiation] {annual:.1f} kWh/m²/yr (avg over {n_years} years)")
    return annual


# ---------------------------------------------------------------------------
# 3.  Hourly capacity factors for representative days  [kW per kWp installed]
# ---------------------------------------------------------------------------

def calc_representative_cf(pvgis_df: pd.DataFrame) -> pd.DataFrame:
    """
    For each representative day, extract the mean hourly capacity factor
    averaged across all years in the PVGIS dataset.

    Capacity factor CF_t = PV_power_W / (peakpower_kWp × 1000)
    Since PVGIS normalises pv_power_W to 1 kWp installed:
        CF_t = pv_power_W / 1000   [kW/kWp]

    Returns a DataFrame with:
        index:   hour of day (0–23)
        columns: season names ('winter', 'spring', 'summer', 'autumn')
        values:  mean CF [kW/kWp], averaged over all years

    Source: PVGIS API documentation – pv_power_W is normalised to 1 kWp
    https://re.jrc.ec.europa.eu/api/v5_2/
    """
    df = pvgis_df.copy()
    df["hour"] = df.index.hour

    cf_dict = {}
    for season, (month, day) in REPRESENTATIVE_DAYS.items():
        # Select the same calendar day across all years
        mask = (df.index.month == month) & (df.index.day == day)
        day_data = df[mask].copy()

        if len(day_data) == 0:
            print(f"[CF] Warning: no data for {season} ({month}/{day}), using zeros")
            cf_dict[season] = pd.Series(0.0, index=range(24))
            continue

        # Mean CF per hour across all years (W → kW, normalised to 1 kWp)
        hourly_cf = day_data.groupby("hour")["pv_power_W"].mean() / 1000
        hourly_cf = hourly_cf.reindex(range(24), fill_value=0.0)
        cf_dict[season] = hourly_cf

        peak = hourly_cf.max()
        print(f"[CF] {season:8s} ({month:02d}/{day:02d}): "
              f"peak CF = {peak:.3f} kW/kWp, "
              f"daily yield = {hourly_cf.sum():.2f} kWh/kWp")

    cf_df = pd.DataFrame(cf_dict)   # shape (24, 4)
    cf_df.index.name = "hour"
    return cf_df


# ---------------------------------------------------------------------------
# 4.  PV potential per building
# ---------------------------------------------------------------------------

def calc_pv_potential(
    buildings: gpd.GeoDataFrame,
    annual_irradiation: float,
    cf_df: pd.DataFrame,
    usable_fraction: float  = USABLE_ROOF_FRACTION,
    panel_efficiency: float = PANEL_EFFICIENCY,
    performance_ratio: float = PERFORMANCE_RATIO,
    min_roof_area: float    = MIN_ROOF_AREA_M2,
) -> gpd.GeoDataFrame:
    """
    For each building compute:

      pv_area_m2       = est_roof_area_m2 × usable_fraction
      peak_power_kwp   = pv_area_m2 × panel_efficiency          [kWp]
      pv_yield_kwh_yr  = peak_power_kwp × Σ_seasons(CF_t × h × w_season)

    The annual yield is derived from the representative-day capacity factors
    rather than from the raw irradiation value, ensuring consistency between
    the annual KPI and the hourly optimiser.

    Also stored per building:
      pv_hourly_{season}_h{HH}  [kWh] – absolute hourly PV output per season
      These are used directly by optimise.py.

    Parameters
    ----------
    cf_df : DataFrame (24 × 4) of capacity factors [kW/kWp] per season
    """
    gdf = buildings.copy()

    # Filter small roofs
    before = len(gdf)
    gdf = gdf[gdf["est_roof_area_m2"] >= min_roof_area].copy()
    print(f"[Filter] Removed {before - len(gdf)} buildings with roof < {min_roof_area} m²"
          f" → {len(gdf):,} remaining")

    # PV system sizing
    gdf["pv_area_m2"]    = gdf["est_roof_area_m2"] * usable_fraction
    gdf["peak_power_kwp"] = gdf["pv_area_m2"] * panel_efficiency

    # Annual yield from representative days
    # Σ_seasons [ Σ_h CF_h × 1h ] × DAYS_PER_SEASON × peak_power_kwp
    annual_cf_sum = cf_df.sum().sum()   # total kWh/kWp across all 4 rep days
    gdf["pv_yield_kwh_yr"] = (
        gdf["peak_power_kwp"] * annual_cf_sum * DAYS_PER_SEASON
    )

    # Hourly PV output per building per season [kWh]
    # Build all columns at once to avoid DataFrame fragmentation warning
    hourly_pv_cols = {}
    for season in REPRESENTATIVE_DAYS:
        for h in range(24):
            cf_val = cf_df.loc[h, season]
            hourly_pv_cols[f"pv_{season}_h{h:02d}"] = gdf["peak_power_kwp"] * cf_val
    gdf = pd.concat([gdf, pd.DataFrame(hourly_pv_cols, index=gdf.index)], axis=1)

    # Cost estimate: 1000 €/kWp (Bundesnetzagentur PV-Monitoring 2024)
    gdf["cost_eur"] = gdf["peak_power_kwp"] * 1000.0

    # Summary
    print(f"\n[PV Potential] Summary:")
    print(f"  Buildings:          {len(gdf):,}")
    print(f"  Total PV area:      {gdf['pv_area_m2'].sum():,.0f} m²")
    print(f"  Total peak power:   {gdf['peak_power_kwp'].sum():,.0f} kWp")
    print(f"  Total annual yield: {gdf['pv_yield_kwh_yr'].sum()/1e6:.2f} GWh/yr")
    print(f"  Mean yield/building:{gdf['pv_yield_kwh_yr'].mean():,.0f} kWh/yr")

    return gdf


# ---------------------------------------------------------------------------
# 5.  Save
# ---------------------------------------------------------------------------

def save_pv_potential(gdf: gpd.GeoDataFrame) -> Path:
    out_path = OUT_DIR / "pv_potential_jork.gpkg"
    gdf.to_file(out_path, driver="GPKG")
    print(f"\n[Saved] PV potential → {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(year_from: int = 2016, year_to: int = 2020) -> gpd.GeoDataFrame:
    """Full pipeline: load → representative CFs → PV potential → save."""
    buildings   = load_buildings()
    pvgis_df    = load_pvgis(year_from, year_to)
    irradiation = calc_annual_irradiation(pvgis_df)
    cf_df       = calc_representative_cf(pvgis_df)
    gdf         = calc_pv_potential(buildings, irradiation, cf_df)
    save_pv_potential(gdf)
    return gdf


if __name__ == "__main__":
    print("=== PV Potential Calculation – Jork / Altes Land ===\n")
    gdf = run()

    print(f"\nColumns: {[c for c in gdf.columns if not c.startswith('pv_winter')][:15]}...")
    print(f"Total hourly PV columns: "
          f"{len([c for c in gdf.columns if c.startswith('pv_')])}")
    print(f"\nTop 5 buildings by annual yield:")
    print(gdf[["building", "area_m2", "peak_power_kwp", "pv_yield_kwh_yr"]]
          .sort_values("pv_yield_kwh_yr", ascending=False).head())