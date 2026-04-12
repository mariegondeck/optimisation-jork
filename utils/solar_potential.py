"""
utils/solar_potential.py

Calculates the annual PV yield potential for each building footprint
in the Jork / Altes Land dataset.

Approach:
  1. Load building footprints (from fetch_gis_data.py output)
  2. Load PVGIS hourly data (from fetch_gis_data.py output)
  3. Derive a single annual irradiation value [kWh/m²/yr] for the region
  4. Per building: annual yield = est_roof_area_m2 × usable_fraction
                                  × panel_efficiency × irradiation
  5. Filter out roofs too small to be worth installing PV
  6. Save enriched GeoDataFrame as GeoPackage for optimizer + Streamlit

Sources:
  - Building footprints: OpenStreetMap, ODbL licence
  - Irradiance data:     EU JRC PVGIS, CC BY 4.0
                         https://re.jrc.ec.europa.eu/pvg_tools/en/
  - Panel efficiency typical values:
    Fraunhofer ISE, Photovoltaics Report 2024
    https://www.ise.fraunhofer.de/en/publications/studies/photovoltaics-report.html
"""

import geopandas as gpd
import pandas as pd
import numpy as np
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths  (robust regardless of working directory)
# ---------------------------------------------------------------------------
ROOT     = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "raw"
OUT_DIR  = ROOT / "data" / "processed"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# PV System parameters
# ---------------------------------------------------------------------------

# Fraction of roof area actually usable for PV panels
# Accounts for: ridge lines, chimneys, shading, edge setbacks
# Typical value: 0.6–0.75 for residential roofs
# Source: Fraunhofer ISE Photovoltaics Report 2024
USABLE_ROOF_FRACTION = 0.65

# Standard crystalline silicon panel efficiency
# Typical commercial module: 0.18–0.22
# Source: Fraunhofer ISE Photovoltaics Report 2024
PANEL_EFFICIENCY = 0.20

# Performance ratio: inverter + cable + temperature losses
# Typical value: 0.75–0.85
# Source: EU JRC PVGIS default loss assumption
PERFORMANCE_RATIO = 0.80

# Minimum usable roof area in m² – smaller roofs are excluded
# (not worth the installation cost)
MIN_ROOF_AREA_M2 = 20.0

# ---------------------------------------------------------------------------
# 1.  Load data
# ---------------------------------------------------------------------------

def load_buildings() -> gpd.GeoDataFrame:
    path = DATA_DIR / "buildings_jork.gpkg"
    if not path.exists():
        raise FileNotFoundError(
            f"Buildings file not found: {path}\n"
            "Run fetch_gis_data.py first."
        )
    gdf = gpd.read_file(path)
    print(f"[Buildings] Loaded {len(gdf)} buildings from {path.name}")
    return gdf


def load_pvgis(year_from: int = 2016, year_to: int = 2020) -> pd.DataFrame:
    path = DATA_DIR / f"pvgis_jork_{year_from}_{year_to}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"PVGIS file not found: {path}\n"
            "Run fetch_gis_data.py first."
        )
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    print(f"[PVGIS]     Loaded {len(df):,} hourly rows from {path.name}")
    return df


# ---------------------------------------------------------------------------
# 2.  Derive annual irradiation [kWh/m²/yr] from PVGIS hourly data
# ---------------------------------------------------------------------------

def calc_annual_irradiation(pvgis_df: pd.DataFrame) -> float:
    """
    Sum up the in-plane irradiance over all hours and average across years.

    poa_direct + poa_sky_diffuse + poa_ground_diffuse = total in-plane [W/m²]
    Multiplying by 1 hour gives Wh/m², dividing by 1000 gives kWh/m².

    Returns: mean annual irradiation in kWh/m²/yr
    """
    # Total in-plane irradiance [W/m²] per hour
    pvgis_df["poa_total"] = (
        pvgis_df["poa_direct"]
        + pvgis_df["poa_sky_diffuse"]
        + pvgis_df["poa_ground_diffuse"]
    )

    # Each row = 1 hour → sum gives Wh/m², divide by 1000 → kWh/m²
    # Then average across the number of years in the dataset
    n_years = pvgis_df.index.year.nunique()
    annual_irradiation = pvgis_df["poa_total"].sum() / 1000 / n_years

    print(f"[Irradiation] Annual in-plane irradiation for Jork: "
          f"{annual_irradiation:.1f} kWh/m²/yr  (averaged over {n_years} years)")
    return annual_irradiation


# ---------------------------------------------------------------------------
# 3.  Calculate PV yield per building
# ---------------------------------------------------------------------------

def calc_pv_potential(
    buildings: gpd.GeoDataFrame,
    annual_irradiation: float,
    usable_fraction: float = USABLE_ROOF_FRACTION,
    panel_efficiency: float = PANEL_EFFICIENCY,
    performance_ratio: float = PERFORMANCE_RATIO,
    min_roof_area: float = MIN_ROOF_AREA_M2,
) -> gpd.GeoDataFrame:
    """
    For each building, estimate:

      pv_area_m2      = est_roof_area_m2 × usable_fraction
      peak_power_kwp  = pv_area_m2 × panel_efficiency    [kWp]
      pv_yield_kwh_yr = pv_area_m2 × panel_efficiency
                        × performance_ratio × annual_irradiation

    Formula source: standard simplified PV yield model,
    consistent with PVGIS methodology.
    https://re.jrc.ec.europa.eu/pvg_tools/en/

    Buildings with est_roof_area_m2 < min_roof_area are excluded.
    """
    gdf = buildings.copy()

    # Filter tiny roofs
    before = len(gdf)
    gdf = gdf[gdf["est_roof_area_m2"] >= min_roof_area].copy()
    print(f"[Filter] Removed {before - len(gdf)} buildings with roof < {min_roof_area} m²"
          f" → {len(gdf)} buildings remaining")

    # PV calculations
    gdf["pv_area_m2"]      = gdf["est_roof_area_m2"] * usable_fraction
    gdf["peak_power_kwp"]  = gdf["pv_area_m2"] * panel_efficiency
    gdf["pv_yield_kwh_yr"] = (
        gdf["pv_area_m2"]
        * panel_efficiency
        * performance_ratio
        * annual_irradiation
    )

    # Normalised yield per m² of roof (useful for ranking / colour scale on map)
    gdf["yield_per_m2"] = gdf["pv_yield_kwh_yr"] / gdf["est_roof_area_m2"]

    print(f"\n[PV Potential] Summary:")
    print(f"  Total buildings:        {len(gdf)}")
    print(f"  Total PV area:          {gdf['pv_area_m2'].sum():,.0f} m²")
    print(f"  Total peak power:       {gdf['peak_power_kwp'].sum():,.0f} kWp")
    print(f"  Total annual yield:     {gdf['pv_yield_kwh_yr'].sum() / 1e6:.2f} GWh/yr")
    print(f"  Mean yield per building:{gdf['pv_yield_kwh_yr'].mean():,.0f} kWh/yr")

    return gdf


# ---------------------------------------------------------------------------
# 4.  Save output
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
    """
    Full pipeline: load → calculate → save.
    Returns the enriched GeoDataFrame (for use in optimizer + Streamlit).
    """
    buildings   = load_buildings()
    pvgis_df    = load_pvgis(year_from, year_to)
    irradiation = calc_annual_irradiation(pvgis_df)
    gdf         = calc_pv_potential(buildings, irradiation)
    save_pv_potential(gdf)
    return gdf


if __name__ == "__main__":
    print("=== PV Potential Calculation – Jork / Altes Land ===\n")
    gdf = run()
    print(f"\nColumns in output: {list(gdf.columns)}")
    print(gdf[["building", "area_m2", "pv_area_m2",
               "peak_power_kwp", "pv_yield_kwh_yr"]].head(10))