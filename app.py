import streamlit as st
import pandas as pd
from datetime import date, timedelta, datetime
import io, os, hashlib

import qrcode
from PIL import Image

# ReportLab (stable PDF generation)
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader


# ----------------------------
# Sustaina MVP v1 (Shipping)
# Professional Certificate + QR + ID + Logo
# ----------------------------

st.set_page_config(page_title="Sustaina — Shipping Risk Brain (MVP)", page_icon="🌊", layout="wide")

st.title("🌊 Sustaina — Shipping Risk Brain (MVP)")
st.caption("Modeled emissions + regulatory/finance risk signals → live dashboard + downloadable certificate")

# --- Sidebar "Login" ---
with st.sidebar:
    st.header("Login (MVP)")
    org = st.text_input("Organization", value="Demo Shipping Ltd")
    user = st.text_input("User", value="Analyst")

    st.divider()
    st.header("Certificate Settings")
    cert_valid_days = st.number_input("Certificate validity (days)", min_value=7, max_value=365, value=90, step=1)
    include_qr = st.checkbox("Include QR verification", value=True)

    st.divider()
    st.header("Brand")
    logo_path = st.text_input("Logo file path", value="assets/logo.png")
    brand_name = st.text_input("Issuer name", value="Sustaina")
    brand_tagline = st.text_input("Tagline", value="Operational Risk & Transition Exposure Certificate")

st.success(f"Logged in as **{user}** at **{org}**")

# ----------------------------
# Reference tables (MODELED)
# ----------------------------
FUEL_EF_CO2 = {  # kg CO2 per kg fuel (tank-to-wake approximations)
    "HFO (Heavy Fuel Oil)": 3.114,
    "MGO/MDO (Marine Gas Oil/Diesel)": 3.206,
    "LNG": 2.750,
    "Methanol (Low-Carbon/Green blend)": 1.375,
    "Ammonia (Green)": 0.000,
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

st.subheader("2) Operating & Route Context (light GPS-style input, not full tracking)")

c4, c5, c6 = st.columns(3)
with c4:
    operating_days = st.number_input("Operating days per year (estimate)", min_value=30, max_value=365, value=300, step=5)
with c5:
    eu_exposure = st.selectbox("Regulatory exposure (EU focus)", ["None", "Partial", "High"], index=1)
with c6:
    route_pattern = st.selectbox("Route pattern", ["Global", "Asia → EU", "Trans-Atlantic", "EU Coastal/Regional", "Other"], index=1)

# optional port-to-port (simple)
st.subheader("3) Voyage Snapshot (optional, improves credibility)")
v1, v2, v3 = st.columns(3)
with v1:
    port_from = st.text_input("From (Port/Region)", value="Singapore")
with v2:
    port_to = st.text_input("To (Port/Region)", value="Rotterdam")
with v3:
    voyage_note = st.text_input("Voyage note (optional)", value="Commercial container route")

# ----------------------------
# Modeled calculations (MVP)
# ----------------------------
speed_mult = {"Slow steaming": 0.80, "Normal": 1.00, "Fast": 1.18}[speed_profile]
base_daily_fuel_tonnes = (dwt / 10000) * 1.2
daily_fuel_tonnes = base_daily_fuel_tonnes * SHIP_TYPE_MULT[ship_type] * speed_mult
annual_fuel_tonnes = daily_fuel_tonnes * operating_days

ef = FUEL_EF_CO2[fuel_type]
annual_co2_tonnes = (annual_fuel_tonnes * 1000 * ef) / 1000  # tonnes

age = date.today().year - int(year_built)
age_risk = min(1.0, max(0.0, (age - 5) / 25))
engine_risk = min(1.0, (ENGINE_RISK[engine_type] - 0.9) / 0.3)
retrofit_risk = {"None": 1.0, "Planned": 0.6, "Installed": 0.3}[retrofit_status]
eu_risk = {"None": 0.2, "Partial": 0.6, "High": 1.0}[eu_exposure]

fuel_pathway_risk = {
    "HFO (Heavy Fuel Oil)": 1.0,
    "MGO/MDO (Marine Gas Oil/Diesel)": 0.9,
    "LNG": 0.75,  # methane risk flagged later
    "Methanol (Low-Carbon/Green blend)": 0.45,
    "Ammonia (Green)": 0.35,
}[fuel_type]

risk_score = 100 * (
    0.30 * eu_risk +
    0.25 * age_risk +
    0.20 * retrofit_risk +
    0.15 * fuel_pathway_risk +
    0.10 * engine_risk
)
risk_score = float(max(0, min(100, risk_score)))

if risk_score >= 75:
    posture = "SEVERE EXPOSURE"
elif risk_score >= 55:
    posture = "HIGH EXPOSURE"
elif risk_score >= 35:
    posture = "MODERATE EXPOSURE"
else:
    posture = "LOWER EXPOSURE"

# Carbon-cost exposure (MODELED proxy band)
carbon_price = {"None": 30, "Partial": 75, "High": 110}[eu_exposure]  # EUR/ton proxy
coverage_mult = 0.0 if eu_exposure == "None" else (0.6 if eu_exposure == "Partial" else 1.0)
annual_cost_est_eur = annual_co2_tonnes * carbon_price * coverage_mult

# range (professional: show as band)
low_band = annual_cost_est_eur * 0.85
high_band = annual_cost_est_eur * 1.15

# Improvement levers (professional, not emotional)
levers = []
if retrofit_status == "None":
    levers.append("Prepare retrofit pathway plan (efficiency / capture-readiness) to reduce compliance friction.")
if eu_exposure in ["Partial", "High"]:
    levers.append("Introduce speed + route efficiency policy to reduce jurisdictional cost exposure.")
if fuel_type in ["HFO (Heavy Fuel Oil)", "MGO/MDO (Marine Gas Oil/Diesel)"]:
    levers.append("Evaluate transition fuel readiness (methanol / ammonia strategy) for medium-term resilience.")
if fuel_type == "LNG":
    levers.append("Flag methane slip as a material risk dimension; add monitoring roadmap (CH4 focus).")
if age >= 20:
    levers.append("High age-profile: strengthen charter/finance narrative using improvement evidence + plan.")

# ----------------------------
# Dashboard
# ----------------------------
st.subheader("Live Dashboard (what banks/insurers/ports understand immediately)")

k1, k2, k3, k4 = st.columns(4)
k1.metric("Risk Score (0–100)", f"{risk_score:.1f}", posture)
k2.metric("Modeled annual fuel (t)", f"{annual_fuel_tonnes:,.0f}")
k3.metric("Modeled annual CO2 (t)", f"{annual_co2_tonnes:,.0f}")
k4.metric("Carbon-cost exposure (EUR, band)", f"{low_band:,.0f} – {high_band:,.0f}")

left, right = st.columns([1.25, 1])
with left:
    st.markdown("### Transparent risk signals (0–1)")
    signals = pd.DataFrame([
        ["Regulatory exposure", eu_risk],
        ["Asset age", age_risk],
        ["Retrofit readiness", retrofit_risk],
        ["Fuel pathway", fuel_pathway_risk],
        ["Engine factor", engine_risk],
    ], columns=["Signal", "Normalized risk (0–1)"])
    st.dataframe(signals, use_container_width=True, hide_index=True)

with right:
    st.markdown("### Improvement pathways")
    if levers:
        for x in levers:
            st.write("•", x)
    else:
        st.write("No major levers detected.")

st.info("All outputs are **modeled decision-support estimates** derived from declared inputs and public factors. The certificate states assumptions clearly.")

# ----------------------------
# Certificate ID + Verification Link
# ----------------------------
def make_cert_id(record: dict) -> str:
    base = f"{record['Organization']}|{record['IMO']}|{record['Vessel name']}|{record['Valid from']}|{record['Valid until']}"
    h = hashlib.sha256(base.encode("utf-8")).hexdigest()[:10].upper()
    return f"SUS-{date.today().year}-{h}"

def make_verification_url(cert_id: str) -> str:
    # MVP: you can replace this later with a real hosted verification page
    # Example later: https://sustaina.io/verify/SUS-2026-XXXX
    return f"https://verify.sustaina.local/{cert_id}"

# ----------------------------
# Professional PDF Certificate (ReportLab)
# ----------------------------
def draw_box(c, x, y, w, h, stroke=1, fill=None):
    if fill is not None:
        c.setFillColor(fill)
        c.rect(x, y, w, h, stroke=stroke, fill=1)
        c.setFillColor(colors.black)
    else:
        c.rect(x, y, w, h, stroke=stroke, fill=0)

def pdf_certificate(record: dict, logo_file: str, with_qr: bool) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4

    # Colors
    navy = colors.HexColor("#0B2E4A")
    blue = colors.HexColor("#0B66C3")
    grey = colors.HexColor("#5B6770")
    light_grey = colors.HexColor("#EEF2F6")

    margin = 18 * mm
    y = H - margin

    # Header band
    c.setFillColor(light_grey)
    c.rect(0, H - 38*mm, W, 38*mm, stroke=0, fill=1)

    # Logo
    logo_ok = False
    if logo_file and os.path.exists(logo_file):
        try:
            img = Image.open(logo_file).convert("RGBA")
            img_reader = ImageReader(img)
            c.drawImage(img_reader, margin, H - 33*mm, width=26*mm, height=26*mm, mask="auto")
            logo_ok = True
        except Exception:
            logo_ok = False

    # Brand text
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(margin + (30*mm if logo_ok else 0), H - 18*mm, record["Issuer"])

    c.setFillColor(grey)
    c.setFont("Helvetica", 10)
    c.drawString(margin + (30*mm if logo_ok else 0), H - 25*mm, record["Tagline"])

    c.setFillColor(grey)
    c.setFont("Helvetica", 9)
    c.drawRightString(W - margin, H - 18*mm, "Decision-Support Document")
    c.drawRightString(W - margin, H - 25*mm, "Not a statutory compliance guarantee")

    y = H - 45*mm

    # Section: Issuer & Validity
    box_h = 22*mm
    draw_box(c, margin, y - box_h, W - 2*margin, box_h, stroke=0, fill=light_grey)
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin + 6*mm, y - 7*mm, "Issuer & Validity")

    c.setFillColor(colors.black)
    c.setFont("Helvetica", 10)

    left_x = margin + 6*mm
    mid_x = margin + (W - 2*margin)/2
    row_y = y - 14*mm

    c.drawString(left_x, row_y, f"Issuer: {record['Issuer']}")
    c.drawString(left_x, row_y - 6*mm, f"Certificate ID: {record['Certificate ID']}")
    c.drawString(mid_x, row_y, f"Issued on: {record['Issued on']}")
    c.drawString(mid_x, row_y - 6*mm, f"Valid until: {record['Valid until']}")

    y -= (box_h + 10*mm)

    # Section: Asset Identification
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin, y, "Asset Identification")
    y -= 6*mm

    table_w = W - 2*margin
    row_h = 7*mm

    fields = [
        ("Organization", record["Organization"]),
        ("Vessel name", record["Vessel name"]),
        ("IMO", record["IMO"]),
        ("Ship type", record["Ship type"]),
        ("Year built", str(record["Year built"])),
        ("DWT", f"{record['DWT']:,}"),
        ("Engine type", record["Engine type"]),
        ("Primary fuel", record["Fuel type"]),
    ]

    # Table header line
    draw_box(c, margin, y - (len(fields)+1)*row_h, table_w, (len(fields)+1)*row_h, stroke=1, fill=None)
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(light_grey)
    c.rect(margin, y - row_h, table_w, row_h, stroke=0, fill=1)
    c.setFillColor(navy)
    c.drawString(margin + 4*mm, y - 5*mm, "Field")
    c.drawString(margin + table_w/2, y - 5*mm, "Value")

    # Rows
    c.setFont("Helvetica", 10)
    c.setFillColor(colors.black)
    yy = y - row_h
    for i, (k, v) in enumerate(fields):
        yy -= row_h
        # subtle row shading
        if i % 2 == 0:
            c.setFillColor(colors.whitesmoke)
            c.rect(margin, yy, table_w, row_h, stroke=0, fill=1)
            c.setFillColor(colors.black)
        c.drawString(margin + 4*mm, yy + 2*mm, str(k))
        c.drawString(margin + table_w/2, yy + 2*mm, str(v))

    y = y - (len(fields)+1)*row_h - 10*mm

    # Section: Operating & Route Context
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin, y, "Operating & Route Context (Declared)")
    y -= 6*mm

    c.setFont("Helvetica", 10)
    c.setFillColor(colors.black)
    context_lines = [
        f"Operating days (annual estimate): {record['Operating days']}",
        f"Speed profile: {record['Speed profile']}",
        f"Route pattern: {record['Route pattern']}",
        f"Voyage snapshot: {record['From']} → {record['To']}",
        f"Regulatory exposure (EU focus): {record['EU exposure']}",
    ]
    for line in context_lines:
        c.drawString(margin, y, line)
        y -= 5*mm

    y -= 4*mm

    # Section: Exposure Summary (big)
    draw_box(c, margin, y - 18*mm, table_w, 18*mm, stroke=1, fill=None)
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin + 4*mm, y - 6*mm, "Exposure Summary")

    c.setFillColor(blue)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(margin + 4*mm, y - 14*mm, f"Risk Score: {record['Risk score']:.1f} / 100")

    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(margin + table_w - 4*mm, y - 14*mm, record["Posture"])

    y -= 26*mm

    # Section: Key Risk Drivers
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin, y, "Key Risk Drivers (Modeled)")
    y -= 6*mm

    c.setFillColor(colors.black)
    c.setFont("Helvetica", 10)
    drivers = record["Drivers"]
    for d in drivers:
        c.drawString(margin + 2*mm, y, f"• {d}")
        y -= 5*mm

    y -= 2*mm

    # Section: Modeled Impact Signals (ranges)
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin, y, "Modeled Impact Signals (Indicative)")
    y -= 6*mm

    c.setFillColor(colors.black)
    c.setFont("Helvetica", 10)
    c.drawString(margin + 2*mm, y, f"• Modeled annual CO2 emissions: ~{record['Annual CO2 (t)']:,.0f} tonnes")
    y -= 5*mm
    c.drawString(margin + 2*mm, y, f"• Carbon-cost exposure band: EUR {record['Cost band low']:,.0f} – {record['Cost band high']:,.0f} per annum")
    y -= 9*mm

    # Section: Improvement Pathways
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin, y, "Improvement Pathways (Actionable)")
    y -= 6*mm

    c.setFillColor(colors.black)
    c.setFont("Helvetica", 10)
    for lev in record["Levers"][:4]:
        c.drawString(margin + 2*mm, y, f"• {lev}")
        y -= 5*mm

    y -= 3*mm

    # Verification block + QR
    if with_qr:
        vurl = record["Verification URL"]
        draw_box(c, margin, 20*mm, table_w, 18*mm, stroke=1, fill=None)
        c.setFillColor(navy)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(margin + 4*mm, 34*mm, "Verification")
        c.setFillColor(colors.black)
        c.setFont("Helvetica", 9)
        c.drawString(margin + 4*mm, 27*mm, f"Certificate ID: {record['Certificate ID']}")
        c.drawString(margin + 4*mm, 23*mm, f"Verification link: {vurl}")

        # QR image
        qr = qrcode.make(vurl)
        qr_img = qr.convert("RGB")
        qr_reader = ImageReader(qr_img)
        c.drawImage(qr_reader, W - margin - 22*mm, 22*mm, width=20*mm, height=20*mm, mask="auto")

    # Footer disclaimer
    c.setFillColor(grey)
    c.setFont("Helvetica", 8)
    disclaimer = (
        "Disclaimer: This certificate is a decision-support output generated from declared inputs and public modeling factors. "
        "It does not replace statutory reporting, accredited verification, or regulator filings. Use alongside "
        "recognized MRV and classification/verification where required."
    )
    c.drawString(margin, 12*mm, disclaimer[:140])
    c.drawString(margin, 8*mm, disclaimer[140:])

    c.showPage()
    c.save()
    return buf.getvalue()


# ----------------------------
# Certificate record
# ----------------------------
st.subheader("Download Certificate (generated from live system state)")

valid_from = date.today()
valid_until = valid_from + timedelta(days=int(cert_valid_days))

record = {
    "Issuer": brand_name.strip(),
    "Tagline": brand_tagline.strip(),
    "Organization": org,
    "Vessel name": vessel_name,
    "IMO": imo,
    "Ship type": ship_type,
    "Year built": int(year_built),
    "DWT": int(dwt),
    "Engine type": engine_type,
    "Fuel type": fuel_type,
    "EU exposure": eu_exposure,
    "Operating days": int(operating_days),
    "Speed profile": speed_profile,
    "Route pattern": route_pattern,
    "From": port_from,
    "To": port_to,
    "Issued on": str(valid_from),
    "Valid from": str(valid_from),
    "Valid until": str(valid_until),
    "Risk score": risk_score,
    "Posture": posture,
    "Annual CO2 (t)": annual_co2_tonnes,
    "Cost band low": float(low_band),
    "Cost band high": float(high_band),
    "Drivers": [
        f"Regulatory exposure: {eu_exposure}",
        f"Fuel pathway: {fuel_type}",
        f"Asset age profile: {age} years",
        f"Retrofit readiness: {retrofit_status}",
        f"Engine factor: {engine_type}",
    ],
    "Levers": levers if levers else ["No major levers detected."],
}

record["Certificate ID"] = make_cert_id(record)
record["Verification URL"] = make_verification_url(record["Certificate ID"])

# Generate PDF bytes
pdf_bytes = pdf_certificate(record, logo_file=logo_path, with_qr=include_qr)

st.download_button(
    label="Download Sustaina Certificate (PDF)",
    data=pdf_bytes,
    file_name=f"{record['Certificate ID']}_Sustaina_Certificate.pdf",
    mime="application/pdf",
    key="download_cert",
)

st.caption("Next upgrades (when ready): Fleet accounts, Evidence upload, Voyage/GPS data intake, Insurer/Banks portal view, Verified MRV connectors.")
