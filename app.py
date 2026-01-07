import streamlit as st
import pandas as pd
from datetime import date, timedelta
from fpdf import FPDF
import io
import qrcode

# ----------------------------
# Sustaina MVP v1 (Shipping)
# ----------------------------

st.set_page_config(page_title="Sustaina — Shipping Risk Brain (MVP)", page_icon="🌊", layout="wide")

st.title("🌊 Sustaina — Shipping Risk Brain (MVP)")
st.caption("Modeled emissions + regulatory/finance risk signals → live dashboard + downloadable certificate (v1)")

# --- Simple "Login" (MVP only) ---
with st.sidebar:
    st.header("Login (MVP)")
    org = st.text_input("Organization", value="Demo Shipping Ltd")
    user = st.text_input("User", value="Analyst")
    st.divider()
    st.header("Certificate settings")
    cert_valid_days = st.number_input("Certificate validity (days)", min_value=7, max_value=365, value=90, step=1)

st.success(f"Logged in as **{user}** at **{org}**")

# ----------------------------
# Reference tables (public factors; modeled, not metered)
# ----------------------------
FUEL_EF_CO2 = {  # kg CO2 per kg fuel (approx typical factors)
    "HFO (Heavy Fuel Oil)": 3.114,
    "MGO/MDO (Marine Gas Oil/Diesel)": 3.206,
    "LNG": 2.750,  # tank-to-wake CO2 only; methane slip handled separately as risk signal
    "Methanol (Green/Low-Carbon)": 1.375,  # depends on pathway; treated as modeled placeholder
    "Ammonia (Green)": 0.000,  # CO2 at exhaust is near-zero; upstream handled separately later
}

SHIP_TYPE_MULT = {
    "Container": 1.15,
    "Bulk carrier": 1.00,
    "Tanker": 1.05,
    "Ro-Ro": 1.10,
    "General cargo": 0.95,
    "Other": 1.00,
}

ENGINE_RISK = {
    "2-stroke low-speed": 1.00,
    "4-stroke medium-speed": 1.05,
    "Dual-fuel": 0.95,
    "Unknown": 1.10,
}

# ----------------------------
# Inputs
# ----------------------------
st.subheader("1) Vessel Profile (input what you know — the system models the rest)")

col1, col2, col3 = st.columns(3)
with col1:
    imo = st.text_input("IMO number", value="IMO1234567")
    vessel_name = st.text_input("Vessel name", value="MV Example")
    ship_type = st.selectbox("Ship type", list(SHIP_TYPE_MULT.keys()), index=0)
with col2:
    year_built = st.number_input("Year built", min_value=1970, max_value=date.today().year, value=2010, step=1)
    dwt = st.number_input("Deadweight tonnage (DWT)", min_value=1000, max_value=400000, value=60000, step=1000)
    engine_type = st.selectbox("Engine type", list(ENGINE_RISK.keys()), index=0)
with col3:
    fuel_type = st.selectbox("Main fuel type", list(FUEL_EF_CO2.keys()), index=0)
    speed_profile = st.selectbox("Typical speed profile", ["Slow steaming", "Normal", "Fast"], index=1)
    retrofit_status = st.selectbox("Retrofit status", ["None", "Planned", "Installed"], index=0)

st.subheader("2) Operating Pattern (simple estimates — we show assumptions clearly)")
col4, col5, col6 = st.columns(3)
with col4:
    operating_days = st.number_input("Operating days per year (estimate)", min_value=30, max_value=365, value=300, step=5)
with col5:
    eu_exposure = st.selectbox("EU exposure", ["None", "Partial", "High"], index=1)
with col6:
    route_region = st.selectbox("Primary route region", ["Global", "EU-focused", "Asia-Europe", "Trans-Atlantic", "Coastal/Regional"], index=0)

# ----------------------------
# Modeled calculations (MVP)
# ----------------------------
# Simple fuel consumption model (placeholder; later upgraded with real telemetry / voyage data)
# Base daily fuel rate depends on DWT + ship type multiplier + speed profile
speed_mult = {"Slow steaming": 0.80, "Normal": 1.00, "Fast": 1.18}[speed_profile]
base_daily_fuel_tonnes = (dwt / 10000) * 1.2  # rough scaling
daily_fuel_tonnes = base_daily_fuel_tonnes * SHIP_TYPE_MULT[ship_type] * speed_mult

annual_fuel_tonnes = daily_fuel_tonnes * operating_days

# Convert fuel tonnes to kg, apply emission factor (kg CO2 per kg fuel) => kg CO2
ef = FUEL_EF_CO2[fuel_type]
annual_co2_tonnes = (annual_fuel_tonnes * 1000 * ef) / 1000  # tonnes CO2

# Risk signals
age = date.today().year - int(year_built)
age_risk = min(1.0, max(0.0, (age - 5) / 25))  # 0..1
engine_risk = min(1.0, (ENGINE_RISK[engine_type] - 0.9) / 0.3)  # normalize-ish
retrofit_risk = {"None": 1.0, "Planned": 0.6, "Installed": 0.3}[retrofit_status]
eu_risk = {"None": 0.2, "Partial": 0.6, "High": 1.0}[eu_exposure]

# Fuel pathway risk (CH4/N2O handled as "attention flags" for now)
fuel_pathway_risk = {
    "HFO (Heavy Fuel Oil)": 1.0,
    "MGO/MDO (Marine Gas Oil/Diesel)": 0.9,
    "LNG": 0.75,  # CO2 lower but methane slip risk -> flagged
    "Methanol (Green/Low-Carbon)": 0.45,
    "Ammonia (Green)": 0.35
}[fuel_type]

# Overall Risk Score (0-100)
risk_score = 100 * (0.30 * eu_risk + 0.25 * age_risk + 0.20 * retrofit_risk + 0.15 * fuel_pathway_risk + 0.10 * engine_risk)
risk_score = float(max(0, min(100, risk_score)))

# Risk posture labels
if risk_score >= 75:
    posture = "Severe exposure"
elif risk_score >= 55:
    posture = "High exposure"
elif risk_score >= 35:
    posture = "Moderate exposure"
else:
    posture = "Lower exposure"

# Cost exposure bands (modeled)
# Use a simple €/t proxy for carbon exposure. This is a placeholder; later connect to live allowance prices.
carbon_price = {"None": 30, "Partial": 75, "High": 110}[eu_exposure]  # €/t proxy (MVP only)
annual_cost_est_eur = annual_co2_tonnes * carbon_price * (0.0 if eu_exposure == "None" else 0.6 if eu_exposure == "Partial" else 1.0)

# Build “improvement levers”
levers = []
if retrofit_status == "None":
    levers.append("Plan retrofit pathway (efficiency / capture readiness) to reduce compliance friction.")
if eu_exposure in ["Partial", "High"]:
    levers.append("Optimize speed + routing strategy to reduce EU carbon-cost exposure.")
if fuel_type in ["HFO (Heavy Fuel Oil)", "MGO/MDO (Marine Gas Oil/Diesel)"]:
    levers.append("Evaluate transition fuel options (methanol / ammonia-ready strategy) for medium-term resilience.")
if fuel_type == "LNG":
    levers.append("Address methane slip risk with engine tuning + monitoring roadmap (CH₄ focus).")
if age >= 20:
    levers.append("Asset age risk is high; prepare charter/finance narrative with improvement plan.")

# ----------------------------
# Dashboard
# ----------------------------
st.subheader("3) Live Dashboard (what banks/insurers/ports can understand)")

k1, k2, k3, k4 = st.columns(4)
k1.metric("Risk Score (0–100)", f"{risk_score:.1f}", posture)
k2.metric("Modeled annual fuel (t)", f"{annual_fuel_tonnes:,.0f}")
k3.metric("Modeled annual CO₂ (t)", f"{annual_co2_tonnes:,.0f}")
k4.metric("Modeled carbon-cost exposure (€)", f"{annual_cost_est_eur:,.0f}")

colA, colB = st.columns([1.2, 1])
with colA:
    st.markdown("### Risk signals (transparent)")
    signals = pd.DataFrame([
        ["EU exposure", eu_risk],
        ["Asset age", age_risk],
        ["Retrofit posture", retrofit_risk],
        ["Fuel pathway", fuel_pathway_risk],
        ["Engine factor", engine_risk],
    ], columns=["Signal", "Normalized risk (0–1)"])
    st.dataframe(signals, use_container_width=True, hide_index=True)

with colB:
    st.markdown("### Improvement levers (actionable)")
    if levers:
        for x in levers:
            st.write("• ", x)
    else:
        st.write("No major levers detected.")

st.info("Important: all values are **modeled estimates** based on declared inputs. The certificate states assumptions explicitly.")

# ----------------------------
# Certificate generator
# ----------------------------
def make_certificate_pdf(record: dict, public_url: str = "") -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, "Sustaina — Risk & Compliance Certificate (MVP)", ln=True)

    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(
        0,
        6,
        "This certificate summarizes modeled emissions and risk exposure signals for decision-use by banks, insurers, ports, and counterparties. "
        "It is not a legal compliance guarantee. Estimates are derived from declared inputs and publicly known factors."
    )

    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Asset Identity", ln=True)
    pdf.set_font("Helvetica", "", 11)

    for k in ["Organization", "Vessel name", "IMO", "Ship type", "Year built", "DWT", "Engine type", "Fuel type", "EU exposure", "Retrofit status"]:
        pdf.cell(55, 6, f"{k}:", 0, 0)
        pdf.multi_cell(0, 6, str(record.get(k, "")))

    pdf.ln(1)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Modeled Results", ln=True)
    pdf.set_font("Helvetica", "", 11)

    rows = [
        ("Risk score (0–100)", f"{record['Risk score']:.1f} ({record['Posture']})"),
        ("Modeled annual fuel (t)", f"{record['Annual fuel (t)']:,.0f}"),
        ("Modeled annual CO₂ (t)", f"{record['Annual CO2 (t)']:,.0f}"),
        ("Modeled carbon-cost exposure (€)", f"{record['Carbon cost (€)']:,.0f}"),
        ("Validity", f"{record['Valid from']} to {record['Valid until']}"),
    ]
    for a, b in rows:
        pdf.cell(70, 6, f"{a}:", 0, 0)
        pdf.multi_cell(0, 6, b)

    pdf.ln(1)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Declared Assumptions (MVP)", ln=True)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(
        0,
        6,
        f"- Operating days/year: {record['Operating days']}\n"
        f"- Primary route region: {record['Route region']}\n"
        f"- Speed profile: {record['Speed profile']}\n"
        f"- This MVP uses a simplified fuel-use model. Future versions integrate telemetry/voyage evidence.\n"
        f"- CH₄ and N₂O are flagged as risk dimensions; quantified accounting requires metered pathways or verified MRV integrations."
    )

    # Optional: QR (only if you later provide a real URL)
    if public_url:
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Verification Link", ln=True)
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 6, f"Live record (QR): {public_url}")

        qr = qrcode.make(public_url)
        buf = io.BytesIO()
        qr.save(buf, format="PNG")
        qr_bytes = buf.getvalue()

        qr_path = "qr_tmp.png"
        with open(qr_path, "wb") as f:
            f.write(qr_bytes)

        pdf.image(qr_path, x=160, y=250, w=35)

    pdf.ln(2)
    pdf.set_font("Helvetica", "I", 9)
    pdf.multi_cell(
        0,
        5,
        "Disclaimer: This certificate is decision-support. It does not replace statutory reporting requirements. "
        "Use alongside accredited verification where required."
    )

    # ✅ Only output at the END (this returns the PDF bytes)
    return pdf.output(dest="S").encode("latin-1", errors="ignore")

