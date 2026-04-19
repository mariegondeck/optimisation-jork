"""
app.py  –  Jork / Altes Land  ·  PV Rooftop Optimiser Dashboard
Pure visualisation – loads pre-computed results, no solver in the app.

Run with:  streamlit run app.py
Pre-compute results with:  python utils/optimise.py
"""

from pathlib import Path

import geopandas as gpd
import pandas as pd
import streamlit as st
import folium
from streamlit_folium import st_folium
import plotly.graph_objects as go
import plotly.express as px

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Syne:wght@400;700;800&display=swap');

  html, body, [class*="css"] { font-family: 'Syne', sans-serif; }
  h1, h2, h3 { font-family: 'Syne', sans-serif; font-weight: 800; }

  section[data-testid="stSidebar"] { background: #0f1923; }
  section[data-testid="stSidebar"] * { color: #e8f4e8 !important; }

  div[data-testid="metric-container"] {
      background: #f7faf7;
      border: 1px solid #c8e6c9;
      border-radius: 10px;
      padding: 1rem 1.2rem;
  }
  div[data-testid="metric-container"] label {
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #2e7d32 !important;
  }
  .header-banner {
      background: linear-gradient(135deg, #1b5e20 0%, #2e7d32 50%, #388e3c 100%);
      padding: 2rem 2.5rem;
      border-radius: 14px;
      margin-bottom: 1.5rem;
      color: white;
  }
  .header-banner h1 { color: white; margin: 0; font-size: 2rem; }
  .header-banner p  { color: #a5d6a7; margin: 0.3rem 0 0; font-size: 0.95rem; }
  .section-label {
      font-size: 0.7rem; font-weight: 700; letter-spacing: 0.12em;
      text-transform: uppercase; color: #2e7d32; margin-bottom: 0.5rem;
  }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

@st.cache_data
def load_results() -> gpd.GeoDataFrame | None:
    path = ROOT / "data" / "processed" / "optimisation_results_jork.gpkg"
    if path.exists():
        return gpd.read_file(path)
    return None


@st.cache_data
def load_pv_potential() -> gpd.GeoDataFrame | None:
    path = ROOT / "data" / "processed" / "pv_potential_jork.gpkg"
    if path.exists():
        return gpd.read_file(path)
    return None


@st.cache_data
def load_pvgis() -> pd.DataFrame | None:
    path = ROOT / "data" / "raw" / "pvgis_jork_2016_2020.csv"
    if path.exists():
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index, utc=True)
        return df
    return None


gdf_results = load_results()
gdf_all     = load_pv_potential()
pvgis_df    = load_pvgis()


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_map, tab_chart, tab_table = st.tabs([
    "🗺️  Map: PV Potential & Results",
    "📈  Irradiance: Time Series",
    "📋  Data: Selected Buildings",
])

# ===========================================================================
# TAB 1 — MAP
# ===========================================================================
with tab_map:

    # KPI row
    col1, col2, col3, col4 = st.columns(4)

    if gdf_results is not None and "selected" in gdf_results.columns:
        sel = gdf_results[gdf_results["selected"] == True]
        col1.metric("Buildings selected",  f"{len(sel):,}")
        col2.metric("Total peak power",    f"{sel['peak_power_kwp'].sum():,.0f} kWp")
        col3.metric("Annual yield",        f"{sel['pv_yield_kwh_yr'].sum()/1e3:,.0f} MWh/yr")
        col4.metric("Est. investment",     f"{sel['cost_eur'].sum()/1e6:.2f} M €")
    elif gdf_all is not None:
        col1.metric("Total buildings",     f"{len(gdf_all):,}")
        col2.metric("Total PV area",       f"{gdf_all['pv_area_m2'].sum():,.0f} m²")
        col3.metric("Max possible yield",  f"{gdf_all['pv_yield_kwh_yr'].sum()/1e3:,.0f} MWh/yr")
        col4.metric("Run optimise.py",     "to see results")
    else:
        st.warning("No data found. Run `utils/solar_potential.py` first.")

    st.markdown("---")

    # Build map
    m = folium.Map(location=[53.5283, 9.6872], zoom_start=13, tiles="CartoDB positron")

    if gdf_results is not None and "selected" in gdf_results.columns:
        show_gdf = gdf_results.to_crs("EPSG:4326")
        st.markdown(
            '<p class="section-label">🟢 Green = selected by optimiser &nbsp;·&nbsp; ⬜ Grey = not selected</p>',
            unsafe_allow_html=True
        )

        def style_result(feature):
            selected = feature["properties"].get("selected", False)
            return {
                "fillColor":   "#2e7d32" if selected else "#9e9e9e",
                "color":       "#1b5e20" if selected else "#757575",
                "weight":      2 if selected else 0.5,
                "fillOpacity": 0.85 if selected else 0.25,
            }

        folium.GeoJson(
            show_gdf.__geo_interface__,
            style_function=style_result,
            tooltip=folium.GeoJsonTooltip(
                fields=["building", "area_m2", "peak_power_kwp", "pv_yield_kwh_yr", "selected"],
                aliases=["Type", "Footprint (m²)", "Peak power (kWp)", "Yield (kWh/yr)", "Selected"],
                localize=True,
            ),
        ).add_to(m)

    elif gdf_all is not None:
        show_gdf = gdf_all.to_crs("EPSG:4326")
        st.markdown(
            '<p class="section-label">Colour = estimated annual PV yield · Run optimise.py to see selected rooftops</p>',
            unsafe_allow_html=True
        )

        q = show_gdf["pv_yield_kwh_yr"].quantile([0.25, 0.5, 0.75, 0.9])

        def yield_color(val):
            if val >= q[0.9]:  return "#1b5e20"
            if val >= q[0.75]: return "#388e3c"
            if val >= q[0.5]:  return "#66bb6a"
            if val >= q[0.25]: return "#a5d6a7"
            return "#e8f5e9"

        def style_pv(feature):
            val = feature["properties"].get("pv_yield_kwh_yr", 0) or 0
            c = yield_color(val)
            return {"fillColor": c, "color": "#2e7d32", "weight": 0.5, "fillOpacity": 0.75}

        folium.GeoJson(
            show_gdf.__geo_interface__,
            style_function=style_pv,
            tooltip=folium.GeoJsonTooltip(
                fields=["building", "area_m2", "pv_yield_kwh_yr", "peak_power_kwp"],
                aliases=["Type", "Footprint (m²)", "Yield (kWh/yr)", "Peak power (kWp)"],
                localize=True,
            ),
        ).add_to(m)

    st_folium(m, width="100%", height=540)

# ===========================================================================
# TAB 2 — IRRADIANCE TIME SERIES
# ===========================================================================
with tab_chart:
    if pvgis_df is None:
        st.warning("No PVGIS data found. Run `utils/fetch_gis_data.py` first.")
    else:
        st.markdown("### Solar irradiance & PV output — Jork (2016–2020)")
        st.caption(
            "Source: EU JRC PVGIS v5.2, SARAH-2 dataset · "
            "lat=53.5283, lon=9.6872 · tilt=35°, azimuth=180° (south)"
        )

        agg = st.radio("Time aggregation", ["Daily", "Monthly", "Annual"], horizontal=True)

        pvgis = pvgis_df.copy()
        pvgis["poa_total"] = (
            pvgis["poa_direct"] + pvgis["poa_sky_diffuse"] + pvgis["poa_ground_diffuse"]
        )

        rules = {"Daily": "D", "Monthly": "ME", "Annual": "YE"}
        labels = {
            "Daily":   ("kWh/m²/day",   "kWh/kWp/day"),
            "Monthly": ("kWh/m²/month", "kWh/kWp/month"),
            "Annual":  ("kWh/m²/yr",    "kWh/kWp/yr"),
        }
        df_plot = pvgis[["poa_total", "pv_power_W"]].resample(rules[agg]).sum() / 1000
        y1_label, y2_label = labels[agg]

        col_a, col_b = st.columns(2)

        with col_a:
            fig1 = go.Figure()
            fig1.add_trace(go.Scatter(
                x=df_plot.index, y=df_plot["poa_total"],
                mode="lines", line=dict(color="#2e7d32", width=1.5),
                fill="tozeroy", fillcolor="rgba(46,125,50,0.12)",
                name="Irradiation",
            ))
            fig1.update_layout(
                title="In-plane irradiation",
                yaxis_title=y1_label,
                plot_bgcolor="white", paper_bgcolor="white",
                font_family="Syne", height=320,
                margin=dict(t=40, b=20, l=10, r=10),
            )
            st.plotly_chart(fig1, use_container_width=True)

        with col_b:
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(
                x=df_plot.index, y=df_plot["pv_power_W"],
                mode="lines", line=dict(color="#f57f17", width=1.5),
                fill="tozeroy", fillcolor="rgba(245,127,23,0.12)",
                name="PV output",
            ))
            fig2.update_layout(
                title="Modelled PV output (1 kWp system)",
                yaxis_title=y2_label,
                plot_bgcolor="white", paper_bgcolor="white",
                font_family="Syne", height=320,
                margin=dict(t=40, b=20, l=10, r=10),
            )
            st.plotly_chart(fig2, use_container_width=True)

        # Seasonal heatmap
        st.markdown("#### Average monthly irradiation by year")
        pvgis["year"]  = pvgis.index.year
        pvgis["month"] = pvgis.index.month
        monthly = (
            pvgis.groupby(["year", "month"])["poa_total"]
            .sum().div(1000).reset_index()
            .pivot(index="year", columns="month", values="poa_total")
        )
        monthly.columns = ["Jan","Feb","Mar","Apr","May","Jun",
                           "Jul","Aug","Sep","Oct","Nov","Dec"]
        fig3 = px.imshow(
            monthly,
            color_continuous_scale=[[0,"#e8f5e9"],[0.5,"#66bb6a"],[1,"#1b5e20"]],
            labels=dict(color="kWh/m²"),
            aspect="auto",
        )
        fig3.update_layout(
            font_family="Syne", height=200,
            margin=dict(t=10, b=10, l=10, r=10),
        )
        st.plotly_chart(fig3, use_container_width=True)

# ===========================================================================
# TAB 3 — DATA TABLE
# ===========================================================================
with tab_table:
    if gdf_results is not None and "selected" in gdf_results.columns:
        sel_df = (
            gdf_results[gdf_results["selected"] == True]
            [[c for c in ["building", "area_m2", "est_roof_area_m2",
                          "pv_area_m2", "peak_power_kwp",
                          "pv_yield_kwh_yr", "cost_eur"]
              if c in gdf_results.columns]]
            .sort_values("pv_yield_kwh_yr", ascending=False)
            .reset_index(drop=True)
        )
        st.markdown(f"### {len(sel_df):,} buildings selected by optimiser")
        st.dataframe(
            sel_df.style.format({
                "area_m2":          "{:.0f}",
                "est_roof_area_m2": "{:.0f}",
                "pv_area_m2":       "{:.0f}",
                "peak_power_kwp":   "{:.2f}",
                "pv_yield_kwh_yr":  "{:,.0f}",
                "cost_eur":         "{:,.0f}",
            }),
            use_container_width=True,
            height=500,
        )
        csv = sel_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇ Download selected buildings (CSV)",
            data=csv,
            file_name="jork_pv_selected_buildings.csv",
            mime="text/csv",
        )
    else:
        st.info("No optimisation results yet. Run `python utils/optimise.py` in your terminal first.")
        if gdf_all is not None:
            st.markdown("#### All buildings with PV potential (top 50 preview)")
            preview = (
                gdf_all[["building","area_m2","peak_power_kwp","pv_yield_kwh_yr"]]
                .sort_values("pv_yield_kwh_yr", ascending=False)
                .head(50).reset_index(drop=True)
            )
            st.dataframe(preview, use_container_width=True)

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown(
    "<small>Data: OpenStreetMap (ODbL) · EU JRC PVGIS CC BY 4.0 · "
    "Solver: CBC via PuLP · Built with Streamlit</small>",
    unsafe_allow_html=True,
)