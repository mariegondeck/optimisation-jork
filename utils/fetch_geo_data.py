"""
utils/fetch_gis_data.py

Fetches GIS data for the Jork / Altes Land region:
  - Building footprints & roof areas  →  OSMnx / Overpass API
  - Solar irradiance time series      →  PVGIS via pvlib (EU JRC)

Sources:
  - OSM / Overpass: https://overpass-api.de  (ODbL licence)
  - osmnx docs:     https://osmnx.readthedocs.io
  - PVGIS API:      https://re.jrc.ec.europa.eu/api/v5_2/
  - pvlib docs:     https://pvlib-python.readthedocs.io
"""

import osmnx as ox           # pip install osmnx
import geopandas as gpd      # pip install geopandas
import pandas as pd
import pvlib                 # pip install pvlib  ← add to requirements.txt!
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PLACE_NAME = "Jork, Landkreis Stade, Niedersachsen, Germany"

# Representative coordinate for Jork town centre (WGS84)
JORK_LAT = 53.5283
JORK_LON = 9.6872

ROOT = Path(__file__).resolve().parent.parent  # geht von utils/ zwei Ebenen hoch
DATA_DIR = ROOT / "data" / "raw"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# 1.  Building footprints from OpenStreetMap  (via osmnx / Overpass)
# ---------------------------------------------------------------------------

def fetch_buildings(place: str = PLACE_NAME) -> gpd.GeoDataFrame:
    """
    Download all building polygons for the given place name.

    Returns a GeoDataFrame in EPSG:25832 (UTM zone 32N – metric, good for Germany)
    with columns:
        geometry             : Polygon / MultiPolygon
        osmid                : OpenStreetMap way/relation ID
        building             : raw OSM building tag  (e.g. 'yes', 'house', 'farm')
        roof:shape           : OSM roof shape tag if present
        area_m2              : footprint area in m²
        est_roof_area_m2     : estimated usable roof area (×1.15 for slight pitch)

    Source: OpenStreetMap contributors, ODbL licence
    https://www.openstreetmap.org/copyright
    """
    print(f"[OSM] Fetching buildings for: {place}")
    gdf = ox.features_from_place(place, tags={"building": True})

    # Keep only polygon geometries (drop point nodes)
    gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()

    # Project to metric CRS for area calculation
    gdf = gdf.to_crs("EPSG:25832")
    gdf["area_m2"] = gdf.geometry.area

    # Roof-area estimate: footprint × 1.15  (≈ 15° pitch correction)
    # For a more accurate model you would use the roof:shape + roof:angle OSM tags
    gdf["est_roof_area_m2"] = gdf["area_m2"] * 1.15

    gdf = gdf.reset_index()
    keep_cols = ["osmid", "geometry", "building", "roof:shape",
                 "area_m2", "est_roof_area_m2"]
    gdf = gdf[[c for c in keep_cols if c in gdf.columns]]

    out_path = DATA_DIR / "buildings_jork.gpkg"
    gdf.to_file(out_path, driver="GPKG")
    print(f"[OSM] Saved {len(gdf)} buildings → {out_path}")
    return gdf


# ---------------------------------------------------------------------------
# 2.  Solar irradiance from PVGIS  –  via pvlib  (fixes 400 BAD REQUEST)
# ---------------------------------------------------------------------------

def fetch_pvgis_hourly(
    lat: float = JORK_LAT,
    lon: float = JORK_LON,
    year_from: int = 2016,
    year_to: int = 2020,
    surface_tilt: float = 35.0,        # degrees from horizontal
    surface_azimuth: float = 180.0,    # pvlib convention: 180 = south
    peakpower: float = 1.0,            # kWp  (1 kWp → normalised output)
    loss: float = 14.0,                # system losses in %
) -> pd.DataFrame:
    """
    Fetch hourly PV production & irradiance data via pvlib's PVGIS wrapper.

    Why pvlib instead of raw requests?
    The PVGIS API uses a non-standard azimuth convention (aspect = azimuth - 180,
    so south = 0, not 180). Our original raw-requests code passed aspect=0.0 which
    PVGIS interpreted as north-facing → rejected with 400 BAD REQUEST.
    pvlib handles this -180 offset internally and is the recommended approach.
    Source: pvlib docs https://pvlib-python.readthedocs.io/en/stable/

    Returns a DataFrame with hourly rows and columns including:
        pv_power_W       : PV power output  [W per kWp installed]
        irradiance_Wm2   : in-plane irradiance  [W/m²]
        temp_air         : 2 m air temperature  [°C]
        wind_speed       : wind speed at 10 m  [m/s]

    Source: EU JRC PVGIS, https://re.jrc.ec.europa.eu/pvg_tools/en/
    Licence: Creative Commons CC BY 4.0
    """
    print(f"[PVGIS] Requesting hourly data via pvlib for lat={lat}, lon={lon} …")

    result = pvlib.iotools.get_pvgis_hourly(
        latitude=lat,
        longitude=lon,
        start=year_from,
        end=year_to,
        surface_tilt=surface_tilt,
        surface_azimuth=surface_azimuth,   # pvlib handles the -180 offset internally
        pvcalculation=True,
        peakpower=peakpower,
        loss=loss,
        components=True,                   # also return beam/diffuse breakdown
        outputformat="json",
        map_variables=True,                # rename to pvlib standard column names
        url="https://re.jrc.ec.europa.eu/api/v5_2/",
        timeout=60,
    )
    df = result[0]

    # Friendly rename for columns we use downstream
    # (map_variables=True may already rename some; this catches both cases)
    rename_map = {
        "P": "pv_power_W",
        "G(i)": "irradiance_Wm2",
        "poa_global": "irradiance_Wm2",
        "T2m": "temp_air",
        "WS10m": "wind_speed",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    out_path = DATA_DIR / f"pvgis_jork_{year_from}_{year_to}.csv"
    df.to_csv(out_path)
    print(f"[PVGIS] Saved {len(df):,} hourly rows → {out_path}")
    print(f"[PVGIS] Columns available: {list(df.columns)}")
    return df


# ---------------------------------------------------------------------------
# 3.  Land-use / agricultural parcels  (Overpass – for No Net Land Take)
# ---------------------------------------------------------------------------

def fetch_landuse(place: str = PLACE_NAME) -> gpd.GeoDataFrame:
    """
    Download land-use polygons (orchards, farmland, residential, …).
    Useful for the 'No Net Land Take' constraint in the optimisation.

    Source: OpenStreetMap contributors, ODbL licence
    """
    print(f"[OSM] Fetching land-use for: {place}")
    gdf = ox.features_from_place(place, tags={"landuse": True})
    gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    gdf = gdf.to_crs("EPSG:25832")
    gdf["area_m2"] = gdf.geometry.area
    gdf = gdf.reset_index()

    out_path = DATA_DIR / "landuse_jork.gpkg"
    gdf.to_file(out_path, driver="GPKG")
    print(f"[OSM] Saved {len(gdf)} land-use polygons → {out_path}")
    return gdf


# ---------------------------------------------------------------------------
# 4.  Street network  (optional – for grid topology / network cost modelling)
# ---------------------------------------------------------------------------

def fetch_street_network(place: str = PLACE_NAME):
    """
    Download the drivable street network for the region.
    Returns (graph, nodes_gdf, edges_gdf) in EPSG:25832.

    Source: OpenStreetMap contributors, ODbL licence
    """
    print(f"[OSM] Fetching street network for: {place}")
    G = ox.graph_from_place(place, network_type="drive")
    G_proj = ox.project_graph(G, to_crs="EPSG:25832")
    nodes, edges = ox.graph_to_gdfs(G_proj)

    out_path = DATA_DIR / "streets_jork.gpkg"
    edges.to_file(out_path, driver="GPKG", layer="edges")
    nodes.to_file(out_path, driver="GPKG", layer="nodes")
    print(f"[OSM] Saved street network → {out_path}")
    return G_proj, nodes, edges


# ---------------------------------------------------------------------------
# Quick test / demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== Fetching GIS data for Jork / Altes Land ===\n")

    buildings = fetch_buildings()
    print(f"\nBuildings overview:\n{buildings[['area_m2', 'est_roof_area_m2']].describe()}\n")

    irradiance = fetch_pvgis_hourly()
    print(f"\nPVGIS columns: {list(irradiance.columns)}")
    print(irradiance.head())

    landuse = fetch_landuse()
    print(f"\nLand-use types:\n{landuse['landuse'].value_counts()}\n")

    print("Done. Files saved to:", DATA_DIR.resolve())