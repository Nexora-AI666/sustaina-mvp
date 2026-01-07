import streamlit as st
import pandas as pd
from datetime import date, timedelta
from fpdf import FPDF

# ============================================================
# Sustaina MVP v1 — Shipping Risk Brain + Certificate (CLEAN)
# ============================================================

st.set_page_config(page_title="Sustaina | Risk Brain MVP", page_icon="🌊", layout="wide")

# ----------------------------
# Helpers
# ----------------------------
def pdf_safe(text: str) -> str:
    """
    fpdf core fonts can't print many unicode characters (—, CO₂, etc).
    This converts to safe ASCII so the PDF never crashes.
    """
    if text is None:
        return ""
    replacements = {
        "—": "-",
        "–": "-",
        "“": '"',
        "”": '"',
        "’": "'",
        "‘": "'",
        "•": "-",
        "₄": "4",
        "₃": "3",
        "₂": "2",
        "₁": "1",
        "€": "EUR ",
        "→": "->",
        "×": "x",
    }
    s = str(text)
    for a, b in replacements.items():
        s = s.replace(a, b)
    return s.encode("latin-1", "ignore").decode("latin-1")

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

# ----------------------------
# Reference factors (MODELED)
# ----------------------------
FUEL_EF_CO2 = {  # kg CO2 per kg fuel (typical factors; MVP placeholder)
    "HFO (Heavy Fuel Oil)": 3.114,
    "MGO/MDO (Marine Gas Oil/Diesel)": 3.206,
    "LNG": 2.750,  # tank-to-wake CO2 only; methane slip treated as risk flag
    "Methanol (Green/Low-Carbon)": 1.375,  # depends on pathway; placeholder
    "Ammonia (Green)": 0.000,  # exhaust CO2 near zero; upstream later
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
# UI Header
# ----------------------------
st.title("🌊 Sustaina — Shipping Risk Brain (MVP)")
st.caption("Modeled emissions + regulatory/finance risk signals -> dashboard + certificate PDF (v1)")

# ----------------------------
# Sidebar: org + certificate settings
# ----------------------------
with st.sidebar:
    st.header("Account (MVP)")
    org = st.text_input("Organization", value="Demo Shipping Ltd")
    user = st.text_input("User", value="Analyst")

    st.divider()
    st.header("Certificate")
    cert_valid_days = st.number_input("Validity (days)", min_value=7, max_value=365, value=90, step=1)

    st.divider()
    st.caption("Tip: This MVP is MODELED. Next versions connect telemetry, voyage evidence and verified MRV.")

st.success(f"Logged in as {user} at {org}")

# ----------------------------
# Inputs
# ----------------------------
st.subheader("1) Vessel Profile (input what you know — system models the rest)")

c1, c2, c3 = st.columns(3)
with c1:
    imo = st.text_input("IMO number", value="IMO1234567")
    vessel_name = st.text_input("Vessel name", value="MV Example")
    ship_type = st.selectbox("Ship type", list(SHIP_TYPE_MULT.keys()), index=0)
with c2:
    year_built = st.number_input("Year built", min_value=1970, max_value=date.today().year, value=2010, step=1)
    dwt = st.number_input("Deadweight tonnage (DWT)", min_value=1000, max_value=400000, value=60000, step=1000)
    engine_type = st.selectbox("Engine type", list(ENGINE_RISK.keys()), index=0)
with c3:
    fuel_type = st.selectbox("Main fuel type", list(FUEL_EF_CO2.keys()), index=0)
    speed_profile = st.selectbox("Typical speed profile", ["Slow steaming", "Normal", "Fast"], index=1)
    retrofit_status = st.selectbox("Retrofit status", ["None", "Planned", "Installed"], index=0)

st.subheader("2) Operating Pattern (simple estimates — assumptions shown clearly)")

c4, c5, c6 = st.columns(3)
with c4:
    operating_days = st.number_input("Operating days per year (estimate)", min_value=30, max_value=365, value=300, step=5)
with c5:
    eu_exposure = st.selectbox("EU exposure", ["None", "Partial", "High"], index=1)
with c6:
    route_region = st.selectbox("Primary route region", ["Global", "EU-focused", "Asia-Europe", "Trans-Atlantic", "Coastal/Regional"], index=0)

# ----------------------------
# MODELED calculations
# ----------------------------
speed_mult = {"Slow steaming": 0.80, "Normal": 1.00, "Fast": 1.18}[speed_profile]

# Rough daily fuel model (placeholder):
base_daily_fuel_tonnes = (dwt / 10000) * 1.2
daily_fuel_tonnes = base_daily_fuel_tonnes * SHIP_TYPE_MULT[ship_type] * speed_mult
annual_fuel_tonnes = daily_fuel_tonnes * operating_days

ef = FUEL_EF_CO2[fuel_type]
annual_co2_tonnes = (annual_fuel_tonnes * 1000 * ef) / 1000  # tonnes CO2

age = date.today().year - int(year_built)

# Normalized risk signals 0..1
age_risk = clamp((age - 5) / 25, 0.0, 1.0)  # older -> higher risk
engine_risk = clamp((ENGINE_RISK[engine_type] - 0.9) / 0.3, 0.0, 1.0)
retrofit_risk = {"None": 1.0, "Planned": 0.6, "Installed": 0.3}[retrofit_status]
eu_risk = {"None": 0.2, "Partial": 0.6, "High": 1.0}[eu_exposure]

fuel_pathway_risk = {
    "HFO (Heavy Fuel Oil)": 1.0,
    "MGO/MDO (Marine Gas Oil/Diesel)": 0.9,
    "LNG": 0.75,                 # methane slip is a risk flag
    "Methanol (Green/Low-Carbon)": 0.45,
    "Ammonia (Green)": 0.35
}[fuel_type]

# Overall risk score 0..100 (transparent weights)
risk_score = 100 * (
    0.30 * eu_risk +
    0.25 * age_risk +
    0.20 * retrofit_risk +
    0.15 * fuel_pathway_risk +
    0.10 * engine_risk
)
risk_score = float(clamp(risk_score, 0.0, 100.0))

if risk_score >= 75:
    posture = "Severe exposure"
elif risk_score >= 55:
    posture = "High exposure"
elif risk_score >= 35:
    posture = "Moderate exposure"
else:
    posture = "Lower exposure"

# Modeled carbon-cost exposure (simple proxy, MVP only)
carbon_price = {"None": 30, "Partial": 75, "High": 110}[eu_exposure]  # EUR/ton proxy
eu_weight = {"None": 0.0, "Partial": 0.6, "High": 1.0}[eu_exposure]
annual_cost_est_eur = annual_co2_tonnes * carbon_price * eu_weight

# Action levers (what makes it useful)
levers = []
if retrofit_status == "None":
    levers.append("Retrofit roadmap: efficiency + capture readiness reduces compliance friction and insurance pressure.")
if eu_exposure in ["Partial", "High"]:
    levers.append("Voyage discipline: speed + routing strategy reduces EU carbon-cost exposure.")
if fuel_type in ["HFO (Heavy Fuel Oil)", "MGO/MDO (Marine Gas Oil/Diesel)"]:
    levers.append("Transition fuel strategy: methanol/ammonia readiness improves bankability and charter access.")
if fuel_type == "LNG":
    levers.append("Methane slip attention: show monitoring plan (CH4 risk).")
if age >= 20:
    levers.append("Older asset: strengthen finance narrative (maintenance + upgrades + rating improvement plan).")

# ----------------------------
# Dashboard
# ----------------------------
st.subheader("3) Live Dashboard (built for banks, insurers, ports)")

k1, k2, k3, k4 = st.columns(4)
k1.metric("Risk Score (0-100)", f"{risk_score:.1f}", posture)
k2.metric("Modeled annual fuel (t)", f"{annual_fuel_tonnes:,.0f}")
k3.metric("Modeled annual CO2 (t)", f"{annual_co2_tonnes:,.0f}")
k4.metric("Modeled carbon-cost exposure (EUR)", f"{annual_cost_est_eur:,.0f}")

left, right = st.columns([1.2, 1])
with left:
    st.markdown("### Risk signals (transparent)")
    signals = pd.DataFrame(
        [
            ["EU exposure", eu_risk],
            ["Asset age", age_risk],
            ["Retrofit posture", retrofit_risk],
            ["Fuel pathway", fuel_pathway_risk],
            ["Engine factor", engine_risk],
        ],
        columns=["Signal", "Normalized risk (0-1)"],
    )
    st.dataframe(signals, use_container_width=True, hide_index=True)

with right:
    st.markdown("### Improvement levers (actionable)")
    if levers:
        for x in levers:
            st.write("- " + x)
    else:
        st.write("No major levers detected.")

st.info("MVP note: outputs are MODELED from declared inputs. Certificate states assumptions clearly.")

# ----------------------------
# Certificate PDF generator
# ----------------------------
def make_certificate_pdf(record: dict) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()

    # Header band
    pdf.set_fill_color(10, 80, 160)  # blue
    pdf.rect(0, 0, 210, 24, "F")

    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_xy(12, 8)
    pdf.cell(0, 8, pdf_safe("Sustaina Certificate"), ln=False)

    pdf.set_xy(12, 16)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, pdf_safe("Risk & Compliance Summary (MODELED)"), ln=False)

    pdf.set_text_color(0, 0, 0)
    pdf.ln(18)

    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(
        0, 6,
        pdf_safe(
            "This certificate summarizes modeled emissions and decision-relevant risk exposure signals for banks, "
            "insurers, ports and counterparties. It is decision-support and not a legal compliance guarantee."
        )
    )
    pdf.ln(2)

    # Identity box
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, pdf_safe("Asset Identity"), ln=True)
    pdf.set_font("Helvetica", "", 11)

    identity_rows = [
        ("Organization", record["Organization"]),
        ("Vessel name", record["Vessel name"]),
        ("IMO", record["IMO"]),
        ("Ship type", record["Ship type"]),
        ("Year built", record["Year built"]),
        ("DWT", record["DWT"]),
        ("Engine type", record["Engine type"]),
        ("Fuel type", record["Fuel type"]),
        ("EU exposure", record["EU exposure"]),
        ("Retrofit status", record["Retrofit status"]),
    ]
    for k, v in identity_rows:
        pdf.cell(55, 6, pdf_safe(f"{k}:"), 0, 0)
        pdf.multi_cell(0, 6, pdf_safe(v))

    pdf.ln(1)

    # Results
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, pdf_safe("Modeled Results"), ln=True)
    pdf.set_font("Helvetica", "", 11)

    results_rows = [
        ("Risk score (0-100)", f'{record["Risk score"]:.1f} ({record["Posture"]})'),
        ("Modeled annual fuel (t)", f'{record["Annual fuel (t)"]:,.0f}'),
        ("Modeled annual CO2 (t)", f'{record["Annual CO2 (t)"]:,.0f}'),
        ("Modeled carbon-cost exposure (EUR)", f'{record["Carbon cost (EUR)"]:,.0f}'),
        ("Validity", f'{record["Valid from"]} to {record["Valid until"]}'),
    ]
    for k, v in results_rows:
        pdf.cell(70, 6, pdf_safe(f"{k}:"), 0, 0)
        pdf.multi_cell(0, 6, pdf_safe(v))

    pdf.ln(1)

    # Assumptions
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, pdf_safe("Declared Assumptions (MVP)"), ln=True)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(
        0, 6,
        pdf_safe(
            f"- Operating days/year: {record['Operating days']}\n"
            f"- Primary route region: {record['Route region']}\n"
            f"- Speed profile: {record['Speed profile']}\n"
            f"- Simplified fuel-use model is used in MVP; later versions integrate telemetry/voyage evidence.\n"
            f"- Methane (CH4) and Nitrous Oxide (N2O) are treated as risk dimensions; quantified accounting requires verified MRV integration."
        )
    )

    pdf.ln(1)
    pdf.set_font("Helvetica", "I", 9)
    pdf.multi_cell(
        0, 5,
        pdf_safe(
            "Disclaimer: This is decision-support output generated from declared inputs and public factors. "
            "It does not replace statutory reporting or accredited verification."
        )
    )

    return pdf.output(dest="S").encode("latin-1", errors="ignore")

# ----------------------------
# Download section
# ----------------------------
st.subheader("4) Download Certificate (generated from live state)")

valid_from = date.today()
valid_until = valid_from + timedelta(days=int(cert_valid_days))

record = {
    "Organization": org,
    "Vessel name": vessel_name,
    "IMO": imo,
    "Ship type": ship_type,
    "Year built": str(int(year_built)),
    "DWT": str(int(dwt)),
    "Engine type": engine_type,
    "Fuel type": fuel_type,
    "EU exposure": eu_exposure,
    "Retrofit status": retrofit_status,
    "Operating days": str(int(operating_days)),
    "Route region": route_region,
    "Speed profile": speed_profile,
    "Risk score": risk_score,
    "Posture": posture,
    "Annual fuel (t)": annual_fuel_tonnes,
    "Annual CO2 (t)": annual_co2_tonnes,
    "Carbon cost (EUR)": annual_cost_est_eur,
    "Valid from": str(valid_from),
    "Valid until": str(valid_until),
}

pdf_bytes = make_certificate_pdf(record)

st.download_button(
    label="Download Sustaina Certificate (PDF)",
    data=pdf_bytes,
    file_name="Sustaina_Certificate.pdf",
    mime="application/pdf",
)

st.caption("Next: fleet view, evidence uploads, voyage/GPS integration, bank/insurer portal view, verified MRV connectors.")
