"""
pages/intro.py  –  Introduction page for the Jork PV Optimiser
"""

from pathlib import Path
import streamlit as st
import base64

ROOT = Path(__file__).resolve().parent.parent

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
  .assumption-box {
      background: #fff8e1;
      border-left: 4px solid #f9a825;
      border-radius: 0 8px 8px 0;
      padding: 0.8rem 1.2rem;
      margin: 0.5rem 0;
      font-size: 0.88rem;
      color: #555;
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
Jork is a municipality in the Altes Land region west of Hamburg. It is one of the largest
contiguous fruit-growing areas in Northern Europe, famous for its apple and cherry orchards.
The landscape is defined by a striking contrast: endless rows of fruit trees, historic
half-timbered farmhouses with thatched roofs, and a network of canals and dikes.
Because of its close proximity to Hamburg, Jork has become increasingly popular as a
residential and leisure destination, attracting visitors and new residents seeking
rural charm near the city.
""")

# ---------------------------------------------------------------------------
# Two-column layout
# ---------------------------------------------------------------------------
col_left, col_right = st.columns([1, 1], gap="large")

with col_left:
    st.markdown("### 📍 Jork")

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
               style="width:200px; height:200px; object-fit:cover; border-radius:50%;
                      border:3px solid #2e7d32; box-shadow:0 4px 12px rgba(0,0,0,0.15);">
          <p style="font-size:1.3rem; color:#666; margin-top:0.5rem;">Town Hall</p>
        </div>
        """, unsafe_allow_html=True)
    with img_col2:
        st.markdown(f"""
        <div style="text-align:center">
          <img src="data:image/jpeg;base64,{img2}"
               style="width:200px; height:200px; object-fit:cover; border-radius:50%;
                      border:3px solid #2e7d32; box-shadow:0 4px 12px rgba(0,0,0,0.15);">
          <p style="font-size:1.3rem; color:#666; margin-top:0.5rem;">Thatched House</p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("#### Key facts about the region")
    facts = [
        ("📐", "Area", "~100 km² (Jork municipality)"),
        ("🏠", "Buildings in dataset", "6,111 (from OpenStreetMap)"),
        ("🍎", "Dominant land use", "Orchard (310 polygons, ~49% of tagged land)"),
        ("☀️", "Annual irradiation", "~970 kWh/m²/yr (PVGIS, 2016–2020 avg.)"),
        ("🌍", "Coordinates", "53.53°N, 9.69°E"),
    ]
    for icon, title, desc in facts:
        st.markdown(f"""
        <div class="constraint-box">
          {icon} <strong>{title}</strong><br>
          <span style="color:#555; font-size:1rem;">{desc}</span>
        </div>
        """, unsafe_allow_html=True)

with col_right:
    st.markdown("### 🎯 Goal")
    st.markdown("""
    This project assesses how different urban growth patterns — **densification vs. sprawl** —
    affect rooftop PV potential, the local supply-demand balance, and key energy system
    indicators by 2030.

    It combines building-level GIS data, hourly PV yield modelling, and a
    **Mixed-Integer Linear Programme (MILP)** that jointly optimises which rooftops
    receive PV panels, how much capacity to install, and how to dispatch energy
    between local PV, grid import, and grid export — hour by hour across
    4 representative days (one per season).
    """)

    st.markdown("#### Optimisation constraints")
    constraints = [
        ("⚡", "Max total installed capacity", "Upper bound on kWp — avoids grid overload"),
        ("📦", "Min viable system size",        "≥ 1 kWp if PV is installed — filters trivial solutions"),
        ("🍎", "No Net Land Take",              "Excludes farm-type buildings on orchard land — core principle of FRACNETcity"),
        ("🔋", "Energy balance per hour",       "Grid import + local PV must cover demand in every time step"),
    ]
    for icon, title, desc in constraints:
        st.markdown(f"""
        <div class="constraint-box">
          {icon} <strong>{title}</strong><br>
          <span style="color:#555; font-size:1rem;">{desc}</span>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("#### Objective function")
    st.code("""
minimise  Σᵢ [ xᵢ·CAPEX_fix + sᵢ·CAPEX_kWp ]
        + Σᵢ Σₜ wₜ · [ gᵢₜ·c_grid − eᵢₜ·c_feedin ]

where:
  xᵢ  ∈ {0,1}      install PV on building i?
  sᵢ  ∈ [0, smax]  installed capacity [kWp]
  gᵢₜ ≥ 0          grid import [kWh] in hour t
  eᵢₜ ≥ 0          feed-in export [kWh] in hour t
  wₜ  = 91.25       days per season (annualisation weight)
    """, language="text")
    st.caption(
        "Prices: grid 0.29 €/kWh (Bundesnetzagentur 2024) · "
        "feed-in 0.082 €/kWh (EEG 2024 ≤10 kWp)"
    )

# ---------------------------------------------------------------------------
# Scenario section
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("### 🏘️ Urban Growth Scenarios (2030 horizon)")

st.markdown("""
Two urban growth scenarios are generated synthetically and compared.
Both add the same number of new buildings (~460, reflecting ~1.5%/yr over 5 years),
but differ in **where** they are placed and **how large** the new buildings are:
""")

sc1, sc2 = st.columns(2)
with sc1:
    st.markdown("""
    <div class="card">
      <h3>🏘️ Densification</h3>
      <p>New buildings placed close to existing ones — infill development
      within already built-up areas. Buildings are <strong>smaller (~120 m²)</strong>,
      typical of terraced or semi-detached housing. Less new land consumed,
      consistent with the <strong>No Net Land Take</strong> principle from FRACNETcity.
      Smaller footprint → less PV potential AND less heating demand.</p>
    </div>
    """, unsafe_allow_html=True)

with sc2:
    st.markdown("""
    <div class="card">
      <h3>🌿 Urban Sprawl</h3>
      <p>New buildings spread outward to the periphery, consuming previously
      undeveloped land including orchard areas. Buildings are
      <strong>larger (~220 m²)</strong>, typical of detached single-family houses.
      Larger footprint → more PV potential BUT also more heating demand.
      Directly illustrates the land consumption problem FRACNETcity addresses.</p>
    </div>
    """, unsafe_allow_html=True)

st.markdown("""
The scenarios are compared on **self-sufficiency**, **self-consumption**, **CO₂ avoided**,
and **net annual energy cost** — showing whether more PV potential from sprawl
actually translates into a better energy outcome once demand is accounted for.
""")

# ---------------------------------------------------------------------------
# Energy demand model
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("### 🌡️ Energy Demand & Dispatch Model")

col_dem1, col_dem2 = st.columns([1, 1], gap="large")

with col_dem1:
    st.markdown("""
    Hourly electricity demand per building is estimated using a
    **Heating Degree Day (HDD)** approach combined with the
    **BDEW H0 residential load profile** for base electricity.
    Temperature data comes from the same PVGIS dataset used for
    solar modelling — ensuring internal consistency.

    For each of the 4 representative days, the model computes
    24 hourly demand values per building:
    """)

    st.code("""
# Heating component (temperature-driven)
Q_heat_h = max(18°C − T_outdoor_h, 0) × U_eff
         × envelope_area / COP_hp         [kWh/h]

# Base component (shaped by BDEW H0 profile)
Q_base_h = BDEW_H0_shape[h] × Q_base_annual / 365

# Total hourly demand
demand_h = Q_heat_h + Q_base_h
    """, language="python")

with col_dem2:
    st.markdown("#### Parameters & sources")
    st.markdown("""
    | Parameter | Value | Source |
    |---|---|---|
    | Heating setpoint | 18 °C | EU EED standard |
    | U-value (envelope) | 0.8 W/m²K | GEG 2020 existing stock |
    | Envelope/footprint ratio | 3.5 | DIN 4108 simplified |
    | Heat pump COP | 3.0 | Fraunhofer ISE 2023 |
    | Base electricity | 40 kWh/m²/yr | BDEW 2023 |
    | Load profile shape | BDEW H0 | BDEW Standardlastprofil 2023 |
    | Temperature data | PVGIS T2m | EU JRC, CC BY 4.0 |
    | Rep. days | 4 × 24 h | one per season |
    """)

    st.markdown("""
    <div class="assumption-box">
      ⚠️ <strong>Key assumption:</strong> All buildings heat via
      air-source heat pumps by 2030 (COP = 3), converting thermal
      demand into electricity. Consistent with Germany's
      Wärmeplanungsgesetz (2024).
    </div>
    """, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("### 📊 Energy KPIs")

k1, k2 = st.columns(2)
with k1:
    st.markdown("""
    <div class="card">
      <h3>⚡ Self-Sufficiency</h3>
      <p>Share of total electricity demand covered by local rooftop PV:<br><br>
      <code>SS = Σ min(PV_i, D_i) / Σ D_i</code><br><br>
      A higher value means the district relies less on grid imports.
      Calculated at building level — community-level sharing would
      yield higher values.</p>
    </div>
    """, unsafe_allow_html=True)

with k2:
    st.markdown("""
    <div class="card">
      <h3>☀️ Self-Consumption</h3>
      <p>Share of local PV production consumed on-site rather than exported:<br><br>
      <code>SC = Σ min(PV_i, D_i) / Σ PV_i</code><br><br>
      Higher with the hourly dispatch model than with annual averages —
      because the optimiser explicitly matches PV production to demand
      hour by hour, reducing unnecessary export.</p>
    </div>
    """, unsafe_allow_html=True)

st.caption(
    "KPI methodology: Luthander et al. (2015), Applied Energy. "
    "https://doi.org/10.1016/j.apenergy.2015.01.014"
)

# ---------------------------------------------------------------------------
# PV yield model
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("### 📐 PV Yield Model")

col_formula, col_params = st.columns([1, 1], gap="large")

with col_formula:
    st.markdown("""
    Annual yield is derived from **hourly capacity factors** for the
    4 representative days — not from a single irradiation value.
    This ensures the map KPI and the optimiser use the same underlying data.
    """)
    st.code("""
# Hourly PV output per building [kWh]
pv_h = peak_power_kwp × CF_h

# where CF_h = pv_power_W / 1000  [kW/kWp]
# from PVGIS, averaged over 2016–2020

# Annual yield (annualised from rep. days)
pv_yield_kwh_yr =
    peak_power_kwp
    × Σ_seasons(Σ_h CF_h)
    × 91.25 days/season
    """, language="python")

with col_params:
    st.markdown("""
    | Parameter | Value | Source |
    |---|---|---|
    | Usable roof fraction | 65% | Fraunhofer ISE PV Report 2024 |
    | Panel efficiency | 20% | Typical crystalline silicon |
    | Performance ratio | 80% | PVGIS default assumptions |
    | Capacity factors | hourly | PVGIS SARAH-2, 2016–2020 |
    | Rep. days | 15 Jan/Apr/Jul/Oct | one per season |
    | Annualisation weight | 91.25 days | 365/4 seasons |
    """)

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
      <p><strong>OpenStreetMap</strong> — building footprints &amp; land use via osmnx<br><br>
      <strong>EU JRC PVGIS</strong> — hourly solar irradiance, PV output &amp; temperature (SARAH-2, 2016–2020)</p>
    </div>
    """, unsafe_allow_html=True)

with c2:
    st.markdown("""
    <div class="card">
      <h3>🗺️ GIS Processing</h3>
      <p><strong>osmnx</strong> — OSM querying<br><br>
      <strong>geopandas</strong> — spatial operations<br><br>
      <strong>EPSG:25832</strong> — UTM zone 32N for metric area calculations</p>
    </div>
    """, unsafe_allow_html=True)

with c3:
    st.markdown("""
    <div class="card">
      <h3>⚙️ Optimisation</h3>
      <p><strong>PuLP</strong> — LP/MIP modelling in Python<br><br>
      <strong>CBC solver</strong> — open-source branch-and-cut (COIN-OR)<br><br>
      <strong>MILP</strong> — binary + continuous variables, hourly dispatch</p>
    </div>
    """, unsafe_allow_html=True)

with c4:
    st.markdown("""
    <div class="card">
      <h3>📊 Visualisation</h3>
      <p><strong>Streamlit</strong> — web dashboard<br><br>
      <strong>Folium</strong> — interactive Leaflet map<br><br>
      <strong>Plotly</strong> — time-series &amp; scenario charts</p>
    </div>
    """, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown(
    "<small>Data: OpenStreetMap (ODbL) · EU JRC PVGIS CC BY 4.0 · "
    "Solver: CBC via PuLP · Built with Streamlit</small>",
    unsafe_allow_html=True,
)