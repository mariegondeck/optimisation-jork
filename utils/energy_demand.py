"""
utils/energy_demand.py

Estimates hourly electricity demand per building for 4 representative days.

Demand components (NO heating assumed — most buildings in Jork still use gas/oil):
  1. Base electricity – appliances, lighting, DHW, washing machines etc.
                        shaped by BDEW H0 residential load profile
  2. Cooling electricity – only 5% of buildings assumed to have air conditioning,
                           scaled by Cooling Degree Days (CDD) from PVGIS temp data

This reflects the realistic 2025/2026 situation in rural northern Germany,
where heat pump adoption is still very low (~1%/yr renovation rate).

Output per building:
  q_total_kwh           – annual total electricity demand [kWh/yr]
  demand_{season}_h{HH} – hourly demand [kWh] per representative day

Representative days (must match solar_potential.py):
  Winter: 15 Jan   Spring: 15 Apr   Summer: 15 Jul   Autumn: 15 Oct

Sources:
  - Base demand: BDEW Standardlastprofil H0 (Haushalt) 2023
    https://www.bdew.de/energie/standardlastprofile-strom/
  - Base demand level: ~40 kWh/m²/yr for German residential
    Statistisches Bundesamt, Energieverbrauch der Haushalte 2023
  - Cooling setpoint & CDD: EN ISO 15927-6
  - AC penetration (~5%): Eurostat cooling statistics Germany 2023
    https://ec.europa.eu/eurostat/statistics-explained/
  - Cooling COP=3: typical split-unit air conditioner
  - Temperature data: EU JRC PVGIS SARAH-2, CC BY 4.0
    https://re.jrc.ec.europa.eu/pvg_tools/en/
  - Representative day methodology:
    Mavromatidis G., Petkov I. (2021). MANGO. Applied Energy 288.
    https://doi.org/10.1016/j.apenergy.2021.116585
"""

import geopandas as gpd
import pandas as pd
import numpy as np
from pathlib import Path

ROOT     = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "raw"
OUT_DIR  = ROOT / "data" / "processed"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Demand parameters
# ---------------------------------------------------------------------------

N_STOREYS          = 1.5    # average storeys (rural Germany)
BASE_DEMAND_PER_M2 = 40.0   # base electricity [kWh/m²/yr]
                             # Haushaltsstrom: Licht, Waschmaschine, Kühlschrank etc.
                             # Source: Statistisches Bundesamt 2023

# Cooling parameters
T_COOL             = 22.0   # cooling setpoint [°C], EN ISO 15927-6
AC_PENETRATION     = 0.05   # 5% of buildings have air conditioning
                             # Source: Eurostat cooling statistics Germany 2023
COOLING_COP        = 3.0    # typical split-unit AC COP
COOLING_W_PER_M2_K = 0.05   # cooling load per m² floor per K above setpoint [W/m²K]

# Heat pump parameters
# ~5% penetration reflects current reality in rural northern Germany (2025)
# Sanierungsrate ~1%/yr since ~2020 → ~5% cumulative
# Source: Bundesverband Wärmepumpe (BWP) Jahresbericht 2024
#   https://www.waermepumpe.de/presse/zahlen-daten/
T_HEAT             = 18.0   # heating setpoint [°C], EU EED standard
HP_PENETRATION     = 0.05   # 5% of buildings have heat pump
U_EFF              = 0.8    # effective U-value [W/m²K], GEG 2020 existing stock
ENVELOPE_RATIO     = 3.5    # envelope/footprint ratio, DIN 4108 simplified
HEAT_PUMP_COP      = 3.0    # ASHP COP, Fraunhofer ISE 2023

# Representative days (must match solar_potential.py)
REPRESENTATIVE_DAYS = {
    "winter": (1, 15),
    "spring": (4, 15),
    "summer": (7, 15),
    "autumn": (10, 15),
}
DAYS_PER_SEASON = 365.0 / 4

# ---------------------------------------------------------------------------
# BDEW H0 normalised residential load profile shape [0–23h]
# Morning peak ~7-9h, evening peak ~18-21h, low overnight
# Source: BDEW Standardlastprofil H0 2023
# https://www.bdew.de/energie/standardlastprofile-strom/
# ---------------------------------------------------------------------------
BDEW_H0_SHAPE = np.array([
    0.026, 0.022, 0.020, 0.019, 0.020, 0.024,   # 00–05
    0.033, 0.048, 0.056, 0.052, 0.047, 0.044,   # 06–11
    0.043, 0.042, 0.041, 0.042, 0.045, 0.052,   # 12–17
    0.060, 0.063, 0.058, 0.050, 0.040, 0.031,   # 18–23
])
BDEW_H0_SHAPE = BDEW_H0_SHAPE / BDEW_H0_SHAPE.sum()


# ---------------------------------------------------------------------------
# 1.  Load data
# ---------------------------------------------------------------------------

def load_buildings() -> gpd.GeoDataFrame:
    path = DATA_DIR / "buildings_jork.gpkg"
    if not path.exists():
        raise FileNotFoundError(f"Not found: {path}\nRun fetch_gis_data.py first.")
    return gpd.read_file(path)


def load_pvgis(year_from: int = 2016, year_to: int = 2020) -> pd.DataFrame:
    path = DATA_DIR / f"pvgis_jork_{year_from}_{year_to}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Not found: {path}\nRun fetch_gis_data.py first.")
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True)
    return df


# ---------------------------------------------------------------------------
# 2.  Representative temperatures
# ---------------------------------------------------------------------------

def calc_representative_temperatures(pvgis_df: pd.DataFrame) -> pd.DataFrame:
    """
    Mean hourly outdoor temperature [°C] for each representative day,
    averaged across all years in the PVGIS dataset.
    Returns DataFrame (24 × 4): index=hour, columns=season names.
    """
    df = pvgis_df.copy()
    df["hour"] = df.index.hour

    temp_dict = {}
    for season, (month, day) in REPRESENTATIVE_DAYS.items():
        mask     = (df.index.month == month) & (df.index.day == day)
        day_data = df[mask]
        hourly_t = day_data.groupby("hour")["temp_air"].mean()
        hourly_t = hourly_t.reindex(range(24), fill_value=0.0)
        temp_dict[season] = hourly_t
        print(f"[Temp] {season:8s}: mean={hourly_t.mean():.1f}°C  "
              f"min={hourly_t.min():.1f}°C  max={hourly_t.max():.1f}°C")

    return pd.DataFrame(temp_dict)   # shape (24, 4)


# ---------------------------------------------------------------------------
# 3.  Cooling profile  [kWh_elec / m²_floor / hour]
# ---------------------------------------------------------------------------

def calc_cooling_profile(temp_df: pd.DataFrame) -> pd.DataFrame:
    """
    Hourly cooling electricity demand per m² floor area [kWh/m²/h].
    Applied only to AC_PENETRATION fraction of buildings.
    """
    cool_df = (
        (temp_df - T_COOL).clip(lower=0)
        * COOLING_W_PER_M2_K / 1000 / COOLING_COP
    )
    for season in REPRESENTATIVE_DAYS:
        daily = cool_df[season].sum()
        if daily > 0:
            print(f"[Cool] {season:8s}: daily={daily*1000:.1f} Wh/m² (5% of buildings)")
    return cool_df


def calc_heating_profile(temp_df: pd.DataFrame) -> pd.DataFrame:
    """
    Hourly heating electricity demand per m² envelope area [kWh/m²/h].
    Converted to electricity via heat pump (COP=3).
    Applied only to HP_PENETRATION fraction of buildings.

    Q_heat_elec_h = max(T_heat - T_outdoor_h, 0) × U_eff / 1000 / COP
    """
    heat_df = (
        (T_HEAT - temp_df).clip(lower=0)
        * U_EFF / 1000 / HEAT_PUMP_COP
    )
    for season in REPRESENTATIVE_DAYS:
        daily = heat_df[season].sum()
        print(f"[Heat] {season:8s}: daily={daily*1000:.1f} Wh/m²_envelope "
              f"(5% of buildings via ASHP)")
    return heat_df


# ---------------------------------------------------------------------------
# 4.  Annual CDD for summary reporting
# ---------------------------------------------------------------------------

def calc_annual_cdd(temp_df: pd.DataFrame) -> float:
    """Approximate annual CDD from representative days."""
    daily_cdd = (temp_df - T_COOL).clip(lower=0).mean()
    annual_cdd = (daily_cdd * 24 * DAYS_PER_SEASON).sum()
    print(f"[CDD] Estimated annual CDD: {annual_cdd:.1f} K·days "
          f"(T_cool={T_COOL}°C)")
    return annual_cdd


# ---------------------------------------------------------------------------
# 5.  Calculate demand per building
# ---------------------------------------------------------------------------

def calc_energy_demand(
    buildings: gpd.GeoDataFrame,
    temp_df: pd.DataFrame,
    heat_profile: pd.DataFrame = None,
    n_storeys: float           = N_STOREYS,
    base_demand_m2: float      = BASE_DEMAND_PER_M2,
    ac_penetration: float      = AC_PENETRATION,
    hp_penetration: float      = HP_PENETRATION,
    cooling_cop: float         = COOLING_COP,
) -> gpd.GeoDataFrame:
    """
    Estimate hourly electricity demand per building.

    Three components:
      1. Base electricity (all buildings): appliances, lighting, DHW
      2. Cooling (5% of buildings): CDD-scaled, via AC
      3. Heating (5% of buildings): HDD-scaled, via heat pump

    Annual totals:
      floor_area_m2     = area_m2 × n_storeys
      envelope_area_m2  = area_m2 × ENVELOPE_RATIO
      q_base_kwh        = base_demand_m2 × floor_area
      q_cooling_kwh     = CDD cooling × floor_area × ac_penetration
      q_heating_kwh     = HDD heating × envelope_area × hp_penetration
      q_total_kwh       = q_base + q_cooling + q_heating
    """
    gdf = buildings.copy()
    cool_profile = calc_cooling_profile(temp_df)
    hp_profile   = calc_heating_profile(temp_df)

    # Building geometry
    gdf["floor_area_m2"]    = gdf["area_m2"] * n_storeys
    gdf["envelope_area_m2"] = gdf["area_m2"] * ENVELOPE_RATIO

    # Annual base demand
    gdf["q_base_kwh"] = base_demand_m2 * gdf["floor_area_m2"]

    # Annual cooling demand
    annual_cool_kwh_m2 = sum(
        cool_profile[s].sum() * DAYS_PER_SEASON
        for s in REPRESENTATIVE_DAYS
    )
    gdf["q_cooling_kwh"] = annual_cool_kwh_m2 * gdf["floor_area_m2"] * ac_penetration

    # Annual heating demand via heat pump (5% of buildings)
    annual_heat_kwh_m2env = sum(
        hp_profile[s].sum() * DAYS_PER_SEASON
        for s in REPRESENTATIVE_DAYS
    )
    gdf["q_heating_kwh"] = (
        annual_heat_kwh_m2env * gdf["envelope_area_m2"] * hp_penetration
    )

    # Total
    gdf["q_total_kwh"] = gdf["q_base_kwh"] + gdf["q_cooling_kwh"] + gdf["q_heating_kwh"]

    # Hourly demand per representative day [kWh]
    hourly_demand_cols = {}
    for season in REPRESENTATIVE_DAYS:
        daily_base = gdf["q_base_kwh"] / 365.0

        for h in range(24):
            # Base (BDEW H0 shaped)
            q_base_h = BDEW_H0_SHAPE[h] * daily_base

            # Cooling (5% of buildings)
            q_cool_h = (cool_profile.loc[h, season]
                        * gdf["floor_area_m2"] * ac_penetration)

            # Heating via heat pump (5% of buildings)
            q_heat_h = (hp_profile.loc[h, season]
                        * gdf["envelope_area_m2"] * hp_penetration)

            hourly_demand_cols[f"demand_{season}_h{h:02d}"] = (
                q_base_h + q_cool_h + q_heat_h
            )

    gdf = pd.concat(
        [gdf, pd.DataFrame(hourly_demand_cols, index=gdf.index)], axis=1
    )

    print(f"\n[Demand] Summary ({len(gdf):,} buildings):")
    print(f"  Mean base demand:    {gdf['q_base_kwh'].mean():,.0f} kWh/yr")
    print(f"  Mean cooling demand: {gdf['q_cooling_kwh'].mean():,.0f} kWh/yr  (5% AC)")
    print(f"  Mean heating demand: {gdf['q_heating_kwh'].mean():,.0f} kWh/yr  (5% ASHP)")
    print(f"  Mean total demand:   {gdf['q_total_kwh'].mean():,.0f} kWh/yr")
    print(f"  Total district:      {gdf['q_total_kwh'].sum()/1e6:.2f} GWh/yr")

    return gdf


# ---------------------------------------------------------------------------
# 6.  KPIs
# ---------------------------------------------------------------------------

def calc_kpis(gdf: gpd.GeoDataFrame) -> dict:
    """
    District-level energy KPIs from annual values.
    Source: Luthander et al. (2015), Applied Energy.
    https://doi.org/10.1016/j.apenergy.2015.01.014
    """
    df = gdf[gdf["selected"] == True].copy() if "selected" in gdf.columns else gdf.copy()
    if len(df) == 0 or "pv_yield_kwh_yr" not in df.columns:
        return {}

    pv_col = "pv_yield_opt_kwh_yr" if "pv_yield_opt_kwh_yr" in df.columns \
             else "pv_yield_kwh_yr"
    total_demand   = df["q_total_kwh"].sum()
    total_pv       = df[pv_col].sum()
    consumed       = df[[pv_col, "q_total_kwh"]].min(axis=1).sum()

    kpis = {
        "total_demand_mwh":  total_demand / 1000,
        "total_pv_mwh":      total_pv / 1000,
        "self_sufficiency":  consumed / total_demand if total_demand > 0 else 0,
        "self_consumption":  consumed / total_pv     if total_pv > 0     else 0,
        "co2_saved_t":       total_pv * 380 / 1e6,
        "pv_surplus_mwh":    (total_pv - consumed) / 1000,
    }
    print(f"\n[KPIs] SS={kpis['self_sufficiency']:.1%}  "
          f"SC={kpis['self_consumption']:.1%}  "
          f"CO₂={kpis['co2_saved_t']:.0f} t/yr")
    return kpis


# ---------------------------------------------------------------------------
# Heating profile stub — kept for API compatibility with scenario_builder.py
# Now returns real values (5% HP penetration)
# ---------------------------------------------------------------------------

def calc_heating_profile_stub(temp_df: pd.DataFrame) -> pd.DataFrame:
    """Alias kept for compatibility — returns real heating profile."""
    return calc_heating_profile(temp_df)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run() -> gpd.GeoDataFrame:
    buildings = load_buildings()
    pvgis_df  = load_pvgis()
    temp_df   = calc_representative_temperatures(pvgis_df)
    _         = calc_annual_cdd(temp_df)
    gdf       = calc_energy_demand(buildings, temp_df)

    out_path  = OUT_DIR / "energy_demand_jork.gpkg"
    save_cols = [c for c in gdf.columns if not c.startswith("demand_")]
    gdf[save_cols].to_file(out_path, driver="GPKG")
    print(f"\n[Saved] → {out_path}")
    return gdf


if __name__ == "__main__":
    print("=== Energy Demand – Jork / Altes Land ===\n")
    print("Model: base electricity + 5% cooling + 5% heat pump heating\n")
    gdf = run()
    print(gdf[["area_m2", "floor_area_m2", "q_base_kwh",
               "q_cooling_kwh", "q_heating_kwh", "q_total_kwh"]].head(5))