"""
pages/intro.py  –  Introduction page for the Jork PV Optimiser
"""

from pathlib import Path
import streamlit as st
import base64

ROOT = Path(__file__).resolve().parent.parent

# https://overpass-turbo.eu/s/2nBX

# ---------------------------------------------------------------------------
# Custom CSS  (same design language as optimiser.py)
# ---------------------------------------------------------------------------
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Syne:wght@400;700;800&display=swap');

  html, body, [class*="css"] { font-family: 'Syne', sans-serif; }
  h1, h2, h3 { font-family: 'Syne', sans-serif; font-weight: 800; }

  .header-banner {
      background: linear-gradient(135deg, #1b5e20 0%, #2e7d32 50%, #388e3c 100%);
      padding: 2rem 2.5rem; border-radius: 14px;
      margin-bottom: 1.5rem; color: white;
  }
  .header-banner h1 { color: white; margin: 0; font-size: 2rem; }
  .header-banner p  { color: #a5d6a7; margin: 0.3rem 0 0; font-size: 0.95rem; }

  .card {
      background: #f7faf7;
      border: 1px solid #c8e6c9;
      border-radius: 12px;
      padding: 1.4rem 1.8rem;
      margin-bottom: 1rem;
  }
  .card h3 { margin-top: 0; color: #1b5e20; font-size: 1.1rem; }
  .card p  { color: #333; line-height: 1.7; margin: 0; }

  .tag {
      display: inline-block;
      background: #e8f5e9;
      color: #2e7d32;
      border: 1px solid #a5d6a7;
      border-radius: 20px;
      padding: 0.2rem 0.8rem;
      font-size: 0.78rem;
      font-weight: 700;
      margin: 0.2rem 0.2rem 0.2rem 0;
      font-family: 'DM Mono', monospace;
  }
  .constraint-box {
      background: white;
      border-left: 4px solid #2e7d32;
      border-radius: 0 8px 8px 0;
      padding: 0.8rem 1.2rem;
      margin: 0.5rem 0;
      font-size: 0.92rem;
      color: #333;
  }
  .stack-item {
      display: flex;
      align-items: flex-start;
      gap: 0.8rem;
      margin-bottom: 0.7rem;
  }
  .stack-icon { font-size: 1.3rem; min-width: 2rem; }
  .stack-text { line-height: 1.5; font-size: 0.92rem; color: #333; }
  .stack-text strong { color: #1b5e20; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown("""
<div class="header-banner">
  <h1>☀️ Jork · Altes Land — PV Rooftop Optimiser</h1>
  <p>A personal project combining GIS data, solar modelling, and binary optimisation in a region I know well</p>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Two-column layout: About Jork  +  About the project
# ---------------------------------------------------------------------------
col_left, col_right = st.columns([1, 1], gap="large")

with col_left:
    st.markdown("### 📍 Jork")

    # Images
    def img_to_base64(path):
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()

    img1 = img_to_base64(ROOT / "assets" / "jork_rathaus.jpg")
    img2 = img_to_base64(ROOT / "assets" / "jork_obsthof.jpeg")

    img_col1, img_col2 = st.columns(2)
    with img_col1:
        st.markdown(f"""
        <div style="text-align:center">
          <img src="data:image/jpeg;base64,{img1}"
               style="width:250px; height:250px; object-fit:cover; border-radius:50%;
                      border:3px solid #2e7d32; box-shadow:0 4px 12px rgba(0,0,0,0.15);">
          <p style="font-size:1.5rem; color:#666; margin-top:0.5rem;">Town Hall</p>
        </div>
        """, unsafe_allow_html=True)
    with img_col2:
        st.markdown(f"""
        <div style="text-align:center">
          <img src="data:image/jpeg;base64,{img2}"
               style="width:250px; height:250px; object-fit:cover; border-radius:50%;
                      border:3px solid #2e7d32; box-shadow:0 4px 12px rgba(0,0,0,0.15);">
          <p style="font-size:1.5rem; color:#666; margin-top:0.5rem;">Thatched House</p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("""
    **Jork** is a municipality in the **Altes Land** region west of Hamburg — one of the largest
    contiguous fruit-growing areas in Northern Europe, famous for its apple and cherry orchards.

    The landscape is defined by a striking contrast: endless rows of fruit trees, historic
    half-timbered farmhouses with large roof surfaces, and a flat topography that makes it
    one of the more solar-friendly regions in northern Germany.

    I grew up near here, which made it the natural choice for a first real spatial optimisation
    project — I know the landscape, the building types, and the tension between agricultural
    preservation and renewable energy development.
    """)

    st.markdown("---")
    st.markdown("### 🎯 The Optimisation Problem")
    st.markdown("""
        The core question this project answers is:

        > **Which combination of rooftops in Jork should receive solar panels
        > to maximise annual energy yield, given real-world constraints?**

        This is formulated as a **Binary Integer Programme (BIP)** — for each of the
        6,000+ buildings, the solver decides whether to install PV (`1`) or not (`0`).
        """)

with col_right:
    st.markdown("#### Key facts about the region")

    facts = {
        "📐 Area": "~100 km² (Jork municipality)",
        "🏠 Buildings in dataset": "6,111 (from OpenStreetMap)",
        "🍎 Dominant land use": "Orchard (310 polygons, ~49% of tagged land)",
        "☀️ Annual irradiation": "~970 kWh/m²/yr (PVGIS, 2016–2020 avg.)",
        "🌍 Coordinates": "53.53°N, 9.69°E",
    }
    for k, v in facts.items():
        st.markdown(f"""
            <div class="constraint-box">
              <strong>{k}:</strong> {v}
            </div>
            """, unsafe_allow_html=True)

    st.markdown("#### Constraints")
    constraints = [
        ("⚡", "Max total installed capacity", "Upper bound on kWp — avoids grid overload"),
        ("🏗️", "Minimum buildings selected", "Ensures geographic distribution"),
        ("🍎", "No Net Land Take", "Excludes farm-type buildings on orchard land — a core principle of the FRACNETcity research framework"),
        ("💶", "Optional budget cap", "Maximum total investment in EUR"),
    ]
    for icon, title, desc in constraints:
        st.markdown(f"""
        <div class="constraint-box">
          {icon} <strong>{title}</strong><br>
          <span style="color:#555; font-size:0.88rem;">{desc}</span>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("#### Objective function")
    st.code("maximise  Σᵢ  xᵢ · pv_yield_kwh_yr_i", language="text")
    st.caption("Where xᵢ ∈ {0,1} is the binary decision for each building i")

# ---------------------------------------------------------------------------
# Technical stack
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("### 🛠️ Technical Stack")

c1, c2, c3, c4 = st.columns(4)

with c1:
    st.markdown("""
    <div class="card">
      <h3>📡 Data Sources</h3>
      <p>
        <strong>OpenStreetMap</strong> — building footprints &amp; land use via osmnx<br><br>
        <strong>EU JRC PVGIS</strong> — hourly solar irradiance &amp; PV output (SARAH-2, 2016–2020)
      </p>
    </div>
    """, unsafe_allow_html=True)

with c2:
    st.markdown("""
    <div class="card">
      <h3>🗺️ GIS Processing</h3>
      <p>
        <strong>osmnx</strong> — OSM querying<br><br>
        <strong>geopandas</strong> — spatial operations<br><br>
        <strong>EPSG:25832</strong> — UTM zone 32N for metric area calculations
      </p>
    </div>
    """, unsafe_allow_html=True)

with c3:
    st.markdown("""
    <div class="card">
      <h3>⚙️ Optimisation</h3>
      <p>
        <strong>PuLP</strong> — LP/MIP modelling in Python<br><br>
        <strong>CBC solver</strong> — open-source branch-and-cut (COIN-OR), bundled with PuLP
      </p>
    </div>
    """, unsafe_allow_html=True)

with c4:
    st.markdown("""
    <div class="card">
      <h3>📊 Visualisation</h3>
      <p>
        <strong>Streamlit</strong> — web dashboard<br><br>
        <strong>Folium</strong> — interactive Leaflet map<br><br>
        <strong>Plotly</strong> — time-series &amp; heatmap charts
      </p>
    </div>
    """, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# PV yield formula
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("### 📐 PV Yield Model")
st.markdown("""
Each building's annual PV yield is estimated using a simplified but standard model,
consistent with the PVGIS methodology:
""")

col_formula, col_params = st.columns([1, 1], gap="large")

with col_formula:
    st.code("""
pv_yield [kWh/yr] =
    est_roof_area_m2
    × usable_fraction   (0.65)
    × panel_efficiency  (0.20)
    × performance_ratio (0.80)
    × annual_irradiation [kWh/m²/yr]
    """, language="text")

with col_params:
    st.markdown("""
    | Parameter | Value | Source |
    |---|---|---|
    | Usable roof fraction | 65% | Fraunhofer ISE PV Report 2024 |
    | Panel efficiency | 20% | Typical crystalline silicon |
    | Performance ratio | 80% | PVGIS default assumptions |
    | Annual irradiation | ~970 kWh/m²/yr | PVGIS SARAH-2 avg. 2016–2020 |
    """)

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown(
    "<small>Data: OpenStreetMap (ODbL) · EU JRC PVGIS CC BY 4.0 · "
    "Solver: CBC via PuLP · Built with Streamlit</small>",
    unsafe_allow_html=True,
)