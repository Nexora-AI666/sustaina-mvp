import io
from datetime import date, timedelta

import pandas as pd
import qrcode
import streamlit as st

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader


# ----------------------------
# Sustaina MVP v1 (Shipping)
# Brain (dashboard) + Certificate (PDF)
# ----------------------------

st.set_page_config(
    page_title="Sustaina — Shipping Risk Brain (MVP)",
    page_icon="🌊",
    layout="wide"
)

st.title("🌊 Sustaina — Shipping Risk Brain (MVP)")
st.caption("Modeled emissions + regulatory/finance risk signals → live dashboard + downloadable certificate")

# ----------------------------
# Sidebar: Login + certificate settings
# ----------------------------
with st.sidebar:
    st.header("Login (MVP)")
    org = st.text_input("Organization", value="Demo Shipping Ltd")
    user = st.text_input("User", value="Analyst")

    st.divider()
    st.header("Certificate settings")
    cert_valid_days = st.number_input(
        "Certificate validity (days)",
        min_value=7,
        max_value=365,
        value=90,
        step=1
    )

st.success(f"Logged in as **{user}** at **{org}**")


# ----------------------------
# Reference tables (MODELED)
# ----------------------------
FUEL_EF_CO2 = {  # kg CO2 per kg fuel (typical factors; modeled)
    "HFO (Heavy Fuel Oil)": 3.114,
    "MGO/MDO (Marine Diesel/Gas Oil)": 3.206,
    "LNG (Tank-to-wake CO2)": 2.750,
    "Methanol (Low/Green mix - modeled)": 1.375,
    "Ammonia (Zero exhaust CO2 - modeled)": 0.000,
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
    year_built = st.number_input(
        "Year built",
        min_value=1970,
        max_value=date.today().year,
        value=2010,
        step=1
    )
    dwt = st.number_input(
        "Deadweight tonnage (DWT)",
        min_value=1000,
        max_value=400000,
        value=60000,
        step=1000
    )
    engine_type = st.selectbox("Engine type", list(ENGINE_RISK.keys()), index=0)

with col3:
    fuel_type = st.selectbox("Main fuel type", list(FUEL_EF_CO2.keys()), index=0)
    speed_profile = st.selectbox("Typical speed profile", ["Slow steaming", "Normal", "Fast"], index=1)
    retrofit_status = st.selectbox("Retrofit status", ["None", "Planned", "Installed"], index=0)

st.subheader("2) Operating Pattern (simple estimates — assumptions are explicit)")
col4, col5, col6 = st.columns(3)
with col4:
    operating_days = st.number_input(
        "Operating days per year (estimate)",
        min_value=30,
        max_value=365,
        value=300,
        step=5
    )
with col5:
    eu_exposure = st.selectbox("EU exposure", ["None", "Partial", "High"], index=1)
with col6:
    route_region = st.selectbox(
        "Primary route region",
        ["Global", "EU-focused", "Asia-Europe", "Trans-Atlantic", "Coastal/Regional"],
        index=0
    )


# ----------------------------
# MODELED calculations (MVP)
# ----------------------------
speed_mult = {"Slow steaming": 0.80, "Normal": 1.00, "Fast": 1.18}[speed_profile]
base_daily_fuel_tonnes = (dwt / 10000) * 1.2  # simple scaling (placeholder)
daily_fuel_tonnes = base_daily_fuel_tonnes * SHIP_TYPE_MULT[ship_type] * speed_mult
annual_fuel_tonnes = daily_fuel_tonnes * operating_days

ef = FUEL_EF_CO2[fuel_type]
annual_co2_tonnes = (annual_fuel_tonnes * 1000 * ef) / 1000  # tonnes CO2

age = date.today().year - int(year_built)
age_risk = min(1.0, max(0.0, (age - 5) / 25))  # 0..1

engine_risk = min(1.0, max(0.0, (ENGINE_RISK[engine_type] - 0.9) / 0.3))  # 0..1
retrofit_risk = {"None": 1.0, "Planned": 0.6, "Installed": 0.3}[retrofit_status]
eu_risk = {"None": 0.2, "Partial": 0.6, "High": 1.0}[eu_exposure]

fuel_pathway_risk = {
    "HFO (Heavy Fuel Oil)": 1.0,
    "MGO/MDO (Marine Diesel/Gas Oil)": 0.9,
    "LNG (Tank-to-wake CO2)": 0.75,  # methane slip flagged later
    "Methanol (Low/Green mix - modeled)": 0.45,
    "Ammonia (Zero exhaust CO2 - modeled)": 0.35
}[fuel_type]

risk_score = 100 * (
    0.30 * eu_risk +
    0.25 * age_risk +
    0.20 * retrofit_risk +
    0.15 * fuel_pathway_risk +
    0.10 * engine_risk
)
risk_score = float(max(0.0, min(100.0, risk_score)))

if risk_score >= 75:
    posture = "Severe exposure"
elif risk_score >= 55:
    posture = "High exposure"
elif risk_score >= 35:
    posture = "Moderate exposure"
else:
    posture = "Lower exposure"

carbon_price_proxy = {"None": 30, "Partial": 75, "High": 110}[eu_exposure]  # EUR/t proxy
scope_mult = 0.0 if eu_exposure == "None" else 0.6 if eu_exposure == "Partial" else 1.0
annual_cost_est_eur = annual_co2_tonnes * carbon_price_proxy * scope_mult


# improvement levers (actionable)
levers = []
if retrofit_status == "None":
    levers.append("Retrofit readiness: plan efficiency / capture-ready roadmap to reduce compliance friction.")
if eu_exposure in ["Partial", "High"]:
    levers.append("Route + speed discipline: reduce EU carbon-cost exposure with operational controls.")
if fuel_type in ["HFO (Heavy Fuel Oil)", "MGO/MDO (Marine Diesel/Gas Oil)"]:
    levers.append("Fuel transition planning: methanol/ammonia-ready strategy for medium-term resilience.")
if fuel_type.startswith("LNG"):
    levers.append("Methane risk: plan engine tuning + monitoring (CH4 focus) for slip management.")
if age >= 20:
    levers.append("Asset age risk: prepare finance/charter narrative + improvement milestones.")


# ----------------------------
# Dashboard
# ----------------------------
st.subheader("3) Live Dashboard (banks / insurers / ports can read this)")

k1, k2, k3, k4 = st.columns(4)
k1.metric("Risk Score (0–100)", f"{risk_score:.1f}", posture)
k2.metric("Modeled annual fuel (t)", f"{annual_fuel_tonnes:,.0f}")
k3.metric("Modeled annual CO2 (t)", f"{annual_co2_tonnes:,.0f}")
k4.metric("Modeled carbon-cost exposure (EUR)", f"{annual_cost_est_eur:,.0f}")

colA, colB = st.columns([1.2, 1])
with colA:
    st.markdown("### Risk signals (transparent)")
    signals = pd.DataFrame(
        [
            ["EU exposure", eu_risk],
            ["Asset age", age_risk],
            ["Retrofit posture", retrofit_risk],
            ["Fuel pathway", fuel_pathway_risk],
            ["Engine factor", engine_risk],
        ],
        columns=["Signal", "Normalized risk (0–1)"]
    )
    st.dataframe(signals, use_container_width=True, hide_index=True)

with colB:
    st.markdown("### Improvement levers (actionable)")
    if levers:
        for x in levers:
            st.write("•", x)
    else:
        st.write("No major levers detected.")

st.info("All values are MODELED estimates based on declared inputs. The certificate states assumptions explicitly.")


# ----------------------------
# Certificate (PDF) — ReportLab (stable)
# ----------------------------
def generate_qr_png_bytes(text: str) -> bytes:
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_certificate_pdf(record: dict, verify_url: str = "") -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    # ---- Header band (simple, professional)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(40, height - 60, "Sustaina — Risk & Compliance Certificate (MVP)")

    c.setFont("Helvetica", 10)
    c.drawString(40, height - 78, "Decision-support certificate for banks, insurers, ports, and counterparties.")

    # ---- Certificate ID (simple deterministic)
    cert_id = f"SUS-{record['IMO']}-{record['Valid from']}"
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, height - 105, f"Certificate ID: {cert_id}")

    c.setFont("Helvetica", 10)
    c.drawString(40, height - 120, f"Issued to: {record['Organization']}  |  Vessel: {record['Vessel name']}  |  IMO: {record['IMO']}")

    # ---- Key results box
    y = height - 160
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "Key Outputs (Modeled)")
    y -= 18

    c.setFont("Helvetica", 11)
    lines = [
        f"Risk score (0–100): {record['Risk score']:.1f}  |  Posture: {record['Posture']}",
        f"Modeled annual fuel (t): {record['Annual fuel (t)']:,.0f}",
        f"Modeled annual CO2 (t): {record['Annual CO2 (t)']:,.0f}",
        f"Modeled carbon-cost exposure (EUR): {record['Carbon cost (EUR)']:,.0f}",
        f"Validity: {record['Valid from']} to {record['Valid until']}",
    ]
    for line in lines:
        c.drawString(50, y, line)
        y -= 16

    # ---- Identity / profile
    y -= 10
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "Asset Profile (Declared)")
    y -= 18

    c.setFont("Helvetica", 10)
    profile_lines = [
        f"Ship type: {record['Ship type']}  |  DWT: {record['DWT']}  |  Year built: {record['Year built']}",
        f"Engine type: {record['Engine type']}  |  Fuel type: {record['Fuel type']}",
        f"EU exposure: {record['EU exposure']}  |  Retrofit status: {record['Retrofit status']}",
        f"Operating days/year: {record['Operating days']}  |  Speed profile: {record['Speed profile']}",
        f"Primary route region: {record['Route region']}",
    ]
    for line in profile_lines:
        c.drawString(50, y, line)
        y -= 14

    # ---- Assumptions / truth section
    y -= 6
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "Assumptions & Truth (MVP)")
    y -= 16

    c.setFont("Helvetica", 9)
    truth_lines = [
        "• This certificate is MODELED from declared inputs + public emission factors (not metered telemetry).",
        "• It is NOT a legal compliance guarantee. It is decision-support for finance/insurance/port risk.",
        "• Future versions integrate voyage evidence, GPS/route data, fuel purchase evidence, and MRV connectors.",
        "• CH4 and N2O are treated as risk dimensions in MVP. Quantified accounting requires verified pathways.",
    ]
    for line in truth_lines:
        c.drawString(50, y, line)
        y -= 12

    # ---- QR verify link (optional)
    if verify_url:
        y -= 8
        c.setFont("Helvetica-Bold", 11)
        c.drawString(40, y, "Verification")
        y -= 14
        c.setFont("Helvetica", 9)
        c.drawString(50, y, verify_url)

        qr_png = generate_qr_png_bytes(verify_url)
        qr_img = ImageReader(io.BytesIO(qr_png))
        c.drawImage(qr_img, width - 140, 60, 90, 90, mask="auto")

    # Footer
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(40, 40, "Sustaina MVP — certificate generated from the live system state. For accredited verification, use an approved verifier.")
    c.showPage()
    c.save()

    return buf.getvalue()


st.subheader("4) Download Certificate (generated from the live system state)")

valid_from = date.today()
valid_until = valid_from + timedelta(days=int(cert_valid_days))

record = {
    "Organization": org,
    "Vessel name": vessel_name,
    "IMO": imo,
    "Ship type": ship_type,
    "Year built": int(year_built),
    "DWT": int(dwt),
    "Engine type": engine_type,
    "Fuel type": fuel_type,
    "EU exposure": eu_exposure,
    "Retrofit status": retrofit_status,
    "Operating days": int(operating_days),
    "Route region": route_region,
    "Speed profile": speed_profile,
    "Risk score": risk_score,
    "Posture": posture,
    "Annual fuel (t)": float(annual_fuel_tonnes),
    "Annual CO2 (t)": float(annual_co2_tonnes),
    "Carbon cost (EUR)": float(annual_cost_est_eur),
    "Valid from": str(valid_from),
    "Valid until": str(valid_until),
}

pdf_bytes = make_certificate_pdf(record, verify_url="")

st.download_button(
    label="Download Sustaina Certificate (PDF)",
    data=pdf_bytes,
    file_name="Sustaina_Certificate.pdf",
    mime="application/pdf"
)

st.caption("Next upgrades: fleets, evidence upload, GPS/voyage inputs, insurer/bank portals, verified MRV connectors.")
