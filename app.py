import streamlit as st
from utils.base_model import calculate_solar_output


st.set_page_config(
    page_title="Solar Ninja — Basic Model",
    page_icon="⚔️",
    layout="centered"
)

st.title("⚔️ Solar Ninja — Basic Model")
st.write(
    "Enter the location and solar system parameters to estimate monthly and annual energy output."
)

with st.form("input_form"):
    st.subheader("Input parameters")

    col1, col2 = st.columns(2)
    latitude = col1.number_input("Latitude (deg)", value=50.45, format="%.4f")
    longitude = col2.number_input("Longitude (deg)", value=30.52, format="%.4f")

    col3, col4 = st.columns(2)
    system_power_kw = col3.number_input("System power (kW)", value=10.0)
    user_tilt = col4.number_input("Panel tilt (deg)", value=45.0)

    submitted = st.form_submit_button("Calculate")

if submitted:
    with st.spinner("Running Solar Ninja calculations..."):
        result = calculate_solar_output(
            latitude=latitude,
            longitude=longitude,
            system_power_kw=system_power_kw,
            user_tilt=user_tilt
        )

    monthly_df = result["monthly_df"]
    monthly_best = result["monthly_best"]
    annual_energy = result["annual_energy"]
    annual_optimal_tilt = result["annual_optimal_tilt"]
    pdf_buffer = result["pdf"]

    st.success("Calculation completed.")

    # Annual summary
    st.subheader("Annual summary")
    colA, colB = st.columns(2)
    colA.metric("Annual energy (user tilt)", f"{annual_energy:,.0f} kWh")
    colB.metric("Annual optimal tilt", f"{annual_optimal_tilt}°")

    # Monthly energy
    st.subheader("Monthly energy (user tilt)")
    st.dataframe(monthly_df)

    # Monthly optimal tilts
    st.subheader("Monthly optimal tilts (analytics)")
    st.dataframe(monthly_best)

    # PDF download
    st.subheader("Download report")
    st.download_button(
        label="Download PDF",
        data=pdf_buffer,
        file_name="solar_ninja_basic_report.pdf",
        mime="application/pdf"
    )

st.markdown("---")
st.markdown(
    """
    ### About  
    **Solar Ninja — Basic Model** is an analytical tool for estimating  
    solar power generation for any location in the world.
    """
)
import pandas as pd
import numpy as np
from pvlib.location import Location
from pvlib import irradiance
import matplotlib.pyplot as plt
from io import BytesIO
import tempfile
import os

# ReportLab (PDF)
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader


def calculate_solar_output(latitude, longitude, system_power_kw, user_tilt):
    """
    Solar Ninja — Basic Model
    PDF через ReportLab (стиль B2, макет P2)

    Основна логіка:
    - Clearsky GHI через Ineichen
    - AOI модель (cos(AOI) з обрізанням ночі)
    - Річний оптимальний кут нахилу (max annual kWh)
    - Генерація при user tilt
    - PNG: графік + PNG таблиця
    - PDF: текст → таблиця → графік
    """

    # ------------------------------------------------------------
    # 1. Часовий індекс
    # ------------------------------------------------------------
    timezone = "UTC"
    times = pd.date_range(
        "2025-01-01", "2025-12-31 23:00",
        freq="1h",
        tz=timezone
    )

    # ------------------------------------------------------------
    # 2. Локація + сонячне положення
    # ------------------------------------------------------------
    location = Location(latitude=latitude, longitude=longitude, tz=timezone)
    solar_position = location.get_solarposition(times)

    # ------------------------------------------------------------
    # 3. Clearsky GHI через Ineichen
    # ------------------------------------------------------------
    clearsky = location.get_clearsky(times, model="ineichen")
    ghi = clearsky["ghi"].copy()
    ghi[ghi < 0] = 0
    ghi_kw = ghi / 1000.0

    # ------------------------------------------------------------
    # 4. Monthly optimal tilts (аналітичні)
    # ------------------------------------------------------------
    tilts = list(range(0, 91))
    monthly_cos_dict = {}

    for tilt in tilts:
        aoi = irradiance.aoi(
            surface_tilt=tilt,
            surface_azimuth=180,
            solar_zenith=solar_position["apparent_zenith"],
            solar_azimuth=solar_position["azimuth"]
        )

        cos_aoi = np.cos(np.radians(aoi))
        cos_aoi[cos_aoi < 0] = 0
        monthly_cos_dict[f"tilt_{tilt}"] = cos_aoi

    df_cos = pd.DataFrame(monthly_cos_dict, index=times)
    monthly_avg = df_cos.resample("M").mean()

    monthly_best = monthly_avg.idxmax(axis=1).str.extract(r"(\d+)").astype(int)
    monthly_best.columns = ["Best Tilt (deg)"]
    monthly_best["Month"] = monthly_best.index.strftime("%B")

    # ------------------------------------------------------------
    # 5. Annual optimal tilt (максимальна річна генерація)
    # ------------------------------------------------------------
    system_losses = 0.20

    best_annual_tilt = None
    best_annual_energy = -1.0

    for tilt in tilts:
        aoi = irradiance.aoi(
            surface_tilt=tilt,
            surface_azimuth=180,
            solar_zenith=solar_position["apparent_zenith"],
            solar_azimuth=solar_position["azimuth"]
        )

        cos_aoi = np.cos(np.radians(aoi))
        cos_aoi[cos_aoi < 0] = 0

        poa = ghi_kw * cos_aoi
        poa *= (1.0 - system_losses)

        hourly_energy = poa * system_power_kw
        annual_energy = float(hourly_energy.sum())

        if annual_energy > best_annual_energy:
            best_annual_energy = annual_energy
            best_annual_tilt = tilt

    annual_optimal_tilt = best_annual_tilt

    # ------------------------------------------------------------
    # 6. Генерація при user tilt
    # ------------------------------------------------------------
    aoi_user = irradiance.aoi(
        surface_tilt=user_tilt,
        surface_azimuth=180,
        solar_zenith=solar_position["apparent_zenith"],
        solar_azimuth=solar_position["azimuth"]
    )

    cos_aoi_user = np.cos(np.radians(aoi_user))
    cos_aoi_user[cos_aoi_user < 0] = 0

    poa_user = ghi_kw * cos_aoi_user
    poa_user *= (1.0 - system_losses)

    hourly_energy_user = poa_user * system_power_kw
    monthly_energy = hourly_energy_user.resample("M").sum()
    annual_energy_user = float(hourly_energy_user.sum())

    monthly_df = pd.DataFrame({
        "Month": monthly_energy.index.strftime("%B"),
        "Energy (kWh)": monthly_energy.values
    })

    # ------------------------------------------------------------
    # 7. Створення графіку PNG
    # ------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(monthly_df["Month"], monthly_df["Energy (kWh)"], color="orange")
    ax.set_title(f"Monthly Energy Output (Tilt = {user_tilt:.1f}°)")
    ax.set_xlabel("Month")
    ax.set_ylabel("Energy (kWh)")
    plt.xticks(rotation=45)
    plt.tight_layout()

    tmp_plot = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    fig.savefig(tmp_plot.name, dpi=150, bbox_inches="tight")
    plt.close(fig)

    # ------------------------------------------------------------
    # 8. Таблиця PNG (Tableau style)
    # ------------------------------------------------------------
    table_fig, table_ax = plt.subplots(figsize=(8, 4))
    table_ax.axis("off")

    table = table_ax.table(
        cellText=monthly_df["Energy (kWh)"].round(2).values.reshape(-1, 1),
        rowLabels=monthly_df["Month"].values,
        colLabels=["Energy (kWh)"],
        cellLoc="center",
        loc="center"
    )

    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.3, 1.4)

    # Style header
    for (row, col), cell in table.get_celld().items():
        if row == 0:
            cell.set_facecolor("#E5E5E5")
            cell.set_text_props(weight="bold")
        else:
            cell.set_facecolor("#FFFFFF")

    tmp_table = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    table_fig.savefig(tmp_table.name, dpi=150, bbox_inches="tight")
    plt.close(table_fig)

    # ------------------------------------------------------------
    # 9. Формування PDF через ReportLab
    # ------------------------------------------------------------
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    y = height - 50
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(50, y, "Solar Ninja — Basic Model Report")

    pdf.setFont("Helvetica", 12)
    y -= 30
    pdf.drawString(50, y, f"Location: lat={latitude:.4f}, lon={longitude:.4f}")
    y -= 18
    pdf.drawString(50, y, f"System power: {system_power_kw:.2f} kW")
    y -= 18
    pdf.drawString(50, y, f"User tilt: {user_tilt:.1f} deg")
    y -= 18
    pdf.drawString(50, y, f"Annual optimal tilt: {annual_optimal_tilt} deg")
    y -= 18
    pdf.drawString(50, y, f"Annual energy (user tilt): {annual_energy_user:.0f} kWh")

    # ------------------------------------------------------------
    # Insert table
    # ------------------------------------------------------------
    y -= 40
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(50, y, "Monthly Energy Table:")
    y -= 20

    pdf.drawImage(ImageReader(tmp_table.name), 50, y - 200, width=400, preserveAspectRatio=True)
    y = y - 220

    # ------------------------------------------------------------
    # New page for plot
    # ------------------------------------------------------------
    pdf.showPage()
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(50, height - 50, "Monthly Energy Chart:")

    pdf.drawImage(ImageReader(tmp_plot.name), 50, height - 450, width=500, preserveAspectRatio=True)

    pdf.save()
    buffer.seek(0)

    # Remove temp files
    os.unlink(tmp_plot.name)
    os.unlink(tmp_table.name)

    # ------------------------------------------------------------
    # Return results
    # ------------------------------------------------------------
    return {
        "monthly_df": monthly_df,
        "monthly_best": monthly_best.reset_index(drop=True),
        "annual_energy": annual_energy_user,
        "annual_optimal_tilt": annual_optimal_tilt,
        "pdf": buffer
    }
