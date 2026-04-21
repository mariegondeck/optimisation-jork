"""
pages/optimiser.py  –  Jork / Altes Land · PV Rooftop Optimiser Dashboard
Pure visualisation – loads pre-computed results from scenario_builder.py.

Run with:        streamlit run app.py
Pre-compute:     python utils/scenario_builder.py
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

GRID_EMISSION_FACTOR_G_KWH = 380.0   # UBA 2023

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
      padding: 2rem 2.5rem; border-radius: 14px;
      margin-bottom: 1.5rem; color: white;
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
# Header
# ---------------------------------------------------------------------------
st.markdown("""
<div class="header-banner">
  <h1>☀️ Jork · Altes Land — PV Rooftop Optimiser</h1>
  <p>MILP optimisation · Hourly dispatch · Urban growth scenarios · OpenStreetMap · PVGIS · CBC Solver</p>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

@st.cache_data
def load_scenario(name: str) -> gpd.GeoDataFrame | None:
    path = ROOT / "data" / "processed" / f"scenario_{name}.gpkg"
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

@st.cache_data
def load_scenario_comparison() -> pd.DataFrame | None:
    path = ROOT / "data" / "processed" / "scenario_comparison.csv"
    if path.exists():
        return pd.read_csv(path)
    return None

gdf_baseline  = load_scenario("baseline")
gdf_dense     = load_scenario("densification")
gdf_sprawl    = load_scenario("sprawl")
pvgis_df      = load_pvgis()
df_comparison = load_scenario_comparison()

# Use baseline as primary result for map + KPI tabs
gdf_main = gdf_baseline

# ---------------------------------------------------------------------------
# Helper: compute KPIs from scenario GeoDataFrame
# ---------------------------------------------------------------------------
def compute_kpis(gdf: gpd.GeoDataFrame) -> dict:
    if gdf is None or len(gdf) == 0:
        return {}
    sel = gdf[gdf["selected"] == True].copy() if "selected" in gdf.columns else gdf.copy()
    if len(sel) == 0:
        return {}

    # Use optimised yield column if available, else fall back
    pv_col = "pv_yield_opt_kwh_yr" if "pv_yield_opt_kwh_yr" in sel.columns \
             else "pv_yield_kwh_yr"

    kpis = {"n_buildings": len(sel)}

    if pv_col in sel.columns:
        total_pv = sel[pv_col].sum()
        kpis["total_pv_mwh"]   = total_pv / 1000
        kpis["co2_saved_t"]    = total_pv * GRID_EMISSION_FACTOR_G_KWH / 1e6

    if "s_opt_kwp" in sel.columns:
        kpis["total_kwp"] = sel["s_opt_kwp"].sum()
    elif "peak_power_kwp" in sel.columns:
        kpis["total_kwp"] = sel["peak_power_kwp"].sum()

    if "capex_eur" in sel.columns:
        kpis["capex_m_eur"] = sel["capex_eur"].sum() / 1e6

    if "annual_cost_eur" in sel.columns:
        kpis["net_annual_cost_eur"] = sel["annual_cost_eur"].sum()

    if "q_total_kwh" in sel.columns and pv_col in sel.columns:
        total_demand   = sel["q_total_kwh"].sum()
        total_pv       = sel[pv_col].sum()
        consumed       = sel[[pv_col, "q_total_kwh"]].min(axis=1).sum()
        kpis["total_demand_mwh"]  = total_demand / 1000
        kpis["self_sufficiency"]  = consumed / total_demand if total_demand > 0 else 0
        kpis["self_consumption"]  = consumed / total_pv     if total_pv > 0     else 0
        kpis["pv_surplus_mwh"]    = (total_pv - consumed) / 1000

    return kpis

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_map, tab_chart, tab_kpi, tab_scenarios, tab_table = st.tabs([
    "🗺️  Map",
    "📈  Irradiance",
    "📊  Energy KPIs",
    "🏘️  Scenarios",
    "📋  Data",
])

# ===========================================================================
# TAB 1 — MAP  (baseline scenario)
# ===========================================================================
with tab_map:

    col1, col2, col3, col4 = st.columns(4)

    if gdf_main is not None and "selected" in gdf_main.columns:
        sel = gdf_main[gdf_main["selected"] == True]
        pv_col = "pv_yield_opt_kwh_yr" if "pv_yield_opt_kwh_yr" in sel.columns \
                 else "pv_yield_kwh_yr"
        kwp_col = "s_opt_kwp" if "s_opt_kwp" in sel.columns else "peak_power_kwp"
        col1.metric("Buildings selected", f"{len(sel):,}")
        col2.metric("Total installed",    f"{sel[kwp_col].sum():,.1f} kWp")
        col3.metric("Annual PV yield",    f"{sel[pv_col].sum()/1e3:,.0f} MWh/yr")
        col4.metric("CAPEX",              f"{sel['capex_eur'].sum()/1e6:.2f} M €"
                    if "capex_eur" in sel.columns else "—")
    else:
        st.info("Run `python utils/scenario_builder.py` to see results.")

    st.markdown("---")
    st.markdown(
        '<p class="section-label">Baseline scenario (today\'s buildings) · '
        '🟢 Green = selected · ⬜ Grey = not selected</p>',
        unsafe_allow_html=True
    )

    m = folium.Map(location=[53.5283, 9.6872], zoom_start=13, tiles="CartoDB positron")

    if gdf_main is not None and "selected" in gdf_main.columns:
        show_gdf = gdf_main.to_crs("EPSG:4326")
        pv_col   = "pv_yield_opt_kwh_yr" if "pv_yield_opt_kwh_yr" in show_gdf.columns \
                   else "pv_yield_kwh_yr"

        def style_result(feature):
            selected = feature["properties"].get("selected", False)
            return {
                "fillColor":   "#2e7d32" if selected else "#9e9e9e",
                "color":       "#1b5e20" if selected else "#757575",
                "weight":      2 if selected else 0.5,
                "fillOpacity": 0.85 if selected else 0.25,
            }

        tt_fields  = [c for c in ["building", "area_m2", "s_opt_kwp",
                                   pv_col, "selected", "annual_cost_eur"]
                      if c in show_gdf.columns]
        tt_aliases = {"building": "Type", "area_m2": "Footprint (m²)",
                      "s_opt_kwp": "Installed (kWp)",
                      "pv_yield_opt_kwh_yr": "Opt. yield (kWh/yr)",
                      "pv_yield_kwh_yr": "Yield (kWh/yr)",
                      "selected": "Selected",
                      "annual_cost_eur": "Net annual cost (€/yr)"}

        folium.GeoJson(
            show_gdf.__geo_interface__,
            style_function=style_result,
            tooltip=folium.GeoJsonTooltip(
                fields=tt_fields,
                aliases=[tt_aliases.get(f, f) for f in tt_fields],
                localize=True,
            ),
        ).add_to(m)

    st_folium(m, width="100%", height=540)

# ===========================================================================
# TAB 2 — IRRADIANCE
# ===========================================================================
with tab_chart:
    if pvgis_df is None:
        st.warning("No PVGIS data found. Run `utils/fetch_gis_data.py` first.")
    else:
        st.markdown("### Solar irradiance & PV output — Jork (2016–2020)")
        st.caption(
            "Source: EU JRC PVGIS v5.2, SARAH-2 · "
            "lat=53.5283, lon=9.6872 · tilt=35°, azimuth=180° (south)"
        )

        agg = st.radio("Time aggregation", ["Daily", "Monthly", "Annual"], horizontal=True)

        pvgis = pvgis_df.copy()
        pvgis["poa_total"] = (
            pvgis["poa_direct"] + pvgis["poa_sky_diffuse"] + pvgis["poa_ground_diffuse"]
        )

        rules  = {"Daily": "D", "Monthly": "ME", "Annual": "YE"}
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
                fill="tozeroy", fillcolor="rgba(46,125,50,0.12)", name="Irradiation",
            ))
            fig1.update_layout(title="In-plane irradiation", yaxis_title=y1_label,
                               plot_bgcolor="white", paper_bgcolor="white",
                               font_family="Syne", height=320,
                               margin=dict(t=40, b=20, l=10, r=10))
            st.plotly_chart(fig1, use_container_width=True)

        with col_b:
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(
                x=df_plot.index, y=df_plot["pv_power_W"],
                mode="lines", line=dict(color="#f57f17", width=1.5),
                fill="tozeroy", fillcolor="rgba(245,127,23,0.12)", name="PV output",
            ))
            fig2.update_layout(title="Modelled PV output (1 kWp system)",
                               yaxis_title=y2_label, plot_bgcolor="white",
                               paper_bgcolor="white", font_family="Syne", height=320,
                               margin=dict(t=40, b=20, l=10, r=10))
            st.plotly_chart(fig2, use_container_width=True)

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
            labels=dict(color="kWh/m²"), aspect="auto",
        )
        fig3.update_layout(font_family="Syne", height=200,
                           margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig3, use_container_width=True)

# ===========================================================================
# TAB 3 — ENERGY KPIs  (baseline)
# ===========================================================================
with tab_kpi:
    st.markdown("### 📊 Energy KPIs — Baseline scenario")

    if gdf_main is not None and "selected" in gdf_main.columns:
        kpis = compute_kpis(gdf_main)

        st.markdown("#### ☀️ Supply")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Buildings with PV", f"{kpis.get('n_buildings', 0):,}")
        c2.metric("Total installed",   f"{kpis.get('total_kwp', 0):,.1f} kWp")
        c3.metric("Annual PV yield",   f"{kpis.get('total_pv_mwh', 0):,.0f} MWh/yr")
        c4.metric("CO₂ avoided",       f"{kpis.get('co2_saved_t', 0):,.0f} t/yr",
                  help="PV yield × 380g CO₂/kWh (UBA 2023)")

        st.markdown("#### 💶 Economics")
        c5, c6 = st.columns(2)
        c5.metric("Total CAPEX",
                  f"{kpis.get('capex_m_eur', 0):.2f} M €",
                  help="Fixed cost (500 €/installation) + 1,000 €/kWp · Bundesnetzagentur 2024")
        c6.metric("Net annual energy cost",
                  f"{kpis.get('net_annual_cost_eur', 0):,.0f} €/yr",
                  help="Grid import costs − feed-in revenue (EEG 2024: 0.082 €/kWh)")

        if "total_demand_mwh" in kpis:
            st.markdown("#### 🌡️ Demand & Balance")
            c7, c8, c9, c10 = st.columns(4)
            c7.metric("Total demand",      f"{kpis['total_demand_mwh']:,.0f} MWh/yr",
                      help="HDD-based, full heat pump adoption by 2030")
            c8.metric("Self-sufficiency",  f"{kpis.get('self_sufficiency', 0):.1%}",
                      help="Luthander et al. (2015)")
            c9.metric("Self-consumption",  f"{kpis.get('self_consumption', 0):.1%}")
            c10.metric("PV surplus",       f"{kpis.get('pv_surplus_mwh', 0):,.0f} MWh/yr",
                       help="Exported to grid")

            # Supply vs Demand chart
            st.markdown("#### Supply vs. Demand")
            pv_consumed = kpis["total_pv_mwh"] - kpis.get("pv_surplus_mwh", 0)
            fig_bar = go.Figure()
            fig_bar.add_trace(go.Bar(
                x=["Total demand", "PV yield", "PV consumed", "PV surplus"],
                y=[kpis["total_demand_mwh"], kpis["total_pv_mwh"],
                   pv_consumed, kpis.get("pv_surplus_mwh", 0)],
                marker_color=["#9e9e9e", "#2e7d32", "#66bb6a", "#a5d6a7"],
                text=[f"{v:,.0f}" for v in [
                    kpis["total_demand_mwh"], kpis["total_pv_mwh"],
                    pv_consumed, kpis.get("pv_surplus_mwh", 0)]],
                textposition="outside",
            ))
            fig_bar.update_layout(
                yaxis_title="MWh/yr", plot_bgcolor="white",
                paper_bgcolor="white", font_family="Syne",
                height=350, margin=dict(t=20, b=20, l=10, r=10),
                showlegend=False,
            )
            st.plotly_chart(fig_bar, use_container_width=True)

        st.caption(
            "⚠️ Key assumption: all buildings heat via ASHP (COP=3) by 2030. "
            "CO₂ factor: 380g/kWh (UBA 2023). "
            "KPI methodology: Luthander et al. (2015), Applied Energy."
        )
    else:
        st.info("Run `python utils/scenario_builder.py` first.")

# ===========================================================================
# TAB 4 — SCENARIOS
# ===========================================================================
with tab_scenarios:
    st.markdown("### 🏘️ Scenario Comparison — Baseline · Densification · Sprawl")
    st.markdown("""
    **Baseline** – today's 6,111 buildings, no new development.
    **Densification** – +460 smaller buildings (~120 m²) close to existing stock.
    **Sprawl** – +460 larger buildings (~220 m²) at the periphery.
    All scenarios use the same MILP optimiser and economic parameters.
    """)

    if df_comparison is not None:

        # Clean display table
        display_cols = {
            "scenario":            "Scenario",
            "n_new":               "New buildings",
            "n_selected":          "PV selected",
            "total_kwp":           "Installed (kWp)",
            "total_pv_mwh":        "PV yield (MWh/yr)",
            "total_demand_mwh":    "Demand (MWh/yr)",
            "self_sufficiency":    "Self-sufficiency",
            "self_consumption":    "Self-consumption",
            "co2_saved_t":         "CO₂ avoided (t/yr)",
            "capex_m_eur":         "CAPEX (M€)",
            "net_annual_cost_eur": "Net annual cost (€/yr)",
        }
        disp = df_comparison[[c for c in display_cols if c in df_comparison.columns]].copy()
        disp = disp.rename(columns=display_cols)

        # Format percentages
        for col in ["Self-sufficiency", "Self-consumption"]:
            if col in disp.columns:
                disp[col] = disp[col].apply(lambda x: f"{float(x):.1%}"
                                            if pd.notna(x) else "—")

        st.dataframe(disp.set_index("Scenario"), use_container_width=True)

        # KPI comparison charts
        st.markdown("#### Key metrics across scenarios")

        numeric_kpis = [
            ("self_sufficiency",    "Self-sufficiency",    "%",       True),
            ("self_consumption",    "Self-consumption",    "%",       True),
            ("total_pv_mwh",        "PV yield (MWh/yr)",  "MWh/yr",  False),
            ("total_demand_mwh",    "Demand (MWh/yr)",    "MWh/yr",  False),
            ("co2_saved_t",         "CO₂ avoided (t/yr)", "t/yr",    False),
            ("net_annual_cost_eur", "Net annual cost (€/yr)", "€/yr", False),
        ]

        scenario_colors = {
            "baseline":       "#9e9e9e",
            "densification":  "#2e7d32",
            "sprawl":         "#e65100",
        }

        col_a, col_b = st.columns(2)
        charts = [k for k in numeric_kpis if k[0] in df_comparison.columns]

        for idx, (col_key, label, unit, is_pct) in enumerate(charts):
            fig = go.Figure()
            for _, row in df_comparison.iterrows():
                sc   = row["scenario"]
                val  = float(row[col_key]) * 100 if is_pct else float(row[col_key])
                fig.add_trace(go.Bar(
                    name=sc.capitalize(),
                    x=[sc.capitalize()],
                    y=[val],
                    marker_color=scenario_colors.get(sc, "#888"),
                    text=[f"{val:.1f}{'%' if is_pct else ''}"],
                    textposition="outside",
                    showlegend=False,
                ))
            fig.update_layout(
                title=label, yaxis_title=unit,
                plot_bgcolor="white", paper_bgcolor="white",
                font_family="Syne", height=280,
                margin=dict(t=40, b=10, l=10, r=10),
            )
            target_col = col_a if idx % 2 == 0 else col_b
            with target_col:
                st.plotly_chart(fig, use_container_width=True)

    else:
        st.info("Run `python utils/scenario_builder.py` to generate scenario results.")

    # Side-by-side maps — rendered via function to avoid closure bugs
    st.markdown("#### Spatial distribution — new buildings highlighted")
    map_col1, map_col2 = st.columns(2)

    def render_scenario_map(container, gdf_sc, label, new_color, map_key):
        with container:
            st.markdown(f"**{label}**")
            if gdf_sc is None:
                st.info("No data yet.")
                return
            m = folium.Map(location=[53.5283, 9.6872], zoom_start=12,
                           tiles="CartoDB positron")
            gdf_wgs = gdf_sc.to_crs("EPSG:4326")
            _nc = new_color

            def _style(feature, nc=_nc):
                is_new = feature["properties"].get("is_new", False)
                sel    = feature["properties"].get("selected", False)
                if is_new:
                    return {"fillColor": nc, "color": nc,
                            "weight": 1.0, "fillOpacity": 0.9}
                elif sel:
                    return {"fillColor": "#2e7d32", "color": "#2e7d32",
                            "weight": 0.5, "fillOpacity": 0.7}
                else:
                    return {"fillColor": "#9e9e9e", "color": "#bbb",
                            "weight": 0.3, "fillOpacity": 0.2}

            tt_fields = [c for c in ["is_new", "selected", "area_m2",
                                     "s_opt_kwp", "pv_yield_opt_kwh_yr"]
                         if c in gdf_wgs.columns]
            folium.GeoJson(
                gdf_wgs.__geo_interface__,
                style_function=_style,
                tooltip=folium.GeoJsonTooltip(
                    fields=tt_fields,
                    aliases=[f.replace("_", " ").title() for f in tt_fields],
                ),
            ).add_to(m)
            st_folium(m, width="100%", height=360, key=map_key)

    render_scenario_map(map_col1, gdf_dense,  "🏘️ Densification", "#2e7d32", "map_dense")
    render_scenario_map(map_col2, gdf_sprawl, "🌿 Sprawl",         "#e65100", "map_sprawl")

# ===========================================================================
# TAB 5 — DATA TABLE  (baseline selected buildings)
# ===========================================================================
with tab_table:

    scenario_choice = st.selectbox(
        "Show data for scenario:",
        ["baseline", "densification", "sprawl"],
        format_func=lambda x: x.capitalize(),
    )
    gdf_choice = load_scenario(scenario_choice)

    if gdf_choice is not None and "selected" in gdf_choice.columns:
        sel_df = gdf_choice[gdf_choice["selected"] == True].copy()

        show_cols = [c for c in [
            "building", "is_new", "area_m2", "est_roof_area_m2",
            "s_opt_kwp", "pv_yield_opt_kwh_yr",
            "q_total_kwh", "capex_eur", "annual_cost_eur",
        ] if c in sel_df.columns]

        sel_df = (
            sel_df[show_cols]
            .sort_values("pv_yield_opt_kwh_yr"
                         if "pv_yield_opt_kwh_yr" in sel_df.columns
                         else show_cols[-1], ascending=False)
            .reset_index(drop=True)
        )

        st.markdown(f"### {len(sel_df):,} buildings selected — {scenario_choice.capitalize()}")

        fmt = {}
        for c in sel_df.columns:
            if c in ("area_m2", "est_roof_area_m2"):    fmt[c] = "{:.0f}"
            elif c in ("s_opt_kwp",):                   fmt[c] = "{:.2f}"
            elif c in ("pv_yield_opt_kwh_yr",
                       "q_total_kwh", "annual_cost_eur",
                       "capex_eur"):                    fmt[c] = "{:,.0f}"

        st.dataframe(sel_df.style.format(fmt),
                     use_container_width=True, height=500)

        csv = sel_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            f"⬇ Download {scenario_choice} selected buildings (CSV)",
            data=csv,
            file_name=f"jork_pv_{scenario_choice}.csv",
            mime="text/csv",
        )
    else:
        st.info("Run `python utils/scenario_builder.py` first.")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown(
    "<small>Data: OpenStreetMap (ODbL) · EU JRC PVGIS CC BY 4.0 · "
    "CO₂ factor: UBA 2023 · Solver: CBC via PuLP · Built with Streamlit</small>",
    unsafe_allow_html=True,
)