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
    """

    # 1. Час
    timezone = "UTC"
    times = pd.date_range(
        "2025-01-01", "2025-12-31 23:00",
        freq="1h",
        tz=timezone
    )

    # 2. Локація
    location = Location(latitude=latitude, longitude=longitude, tz=timezone)
    solar_position = location.get_solarposition(times)

    # 3. Clearsky
    clearsky = location.get_clearsky(times, model="ineichen")
    ghi = clearsky["ghi"].clip(lower=0)
    ghi_kw = ghi / 1000.0

    # 4. Monthly optimal tilt
    tilts = list(range(0, 91))
    monthly_cos = {}

    for t in tilts:
        aoi = irradiance.aoi(
            surface_tilt=t,
            surface_azimuth=180,
            solar_zenith=solar_position["apparent_zenith"],
            solar_azimuth=solar_position["azimuth"]
        )
        cos_aoi = np.cos(np.radians(aoi))
        cos_aoi[cos_aoi < 0] = 0
        monthly_cos[f"tilt_{t}"] = cos_aoi

    df_cos = pd.DataFrame(monthly_cos, index=times)
    monthly_avg = df_cos.resample("M").mean()

    monthly_best = monthly_avg.idxmax(axis=1).str.extract(r"(\d+)").astype(int)
    monthly_best.columns = ["Best Tilt (deg)"]
    monthly_best["Month"] = monthly_best.index.strftime("%B")

    # 5. Annual optimal tilt
    system_losses = 0.20
    best_tilt = None
    best_energy = -1

    for t in tilts:
        aoi = irradiance.aoi(
            surface_tilt=t,
            surface_azimuth=180,
            solar_zenith=solar_position["apparent_zenith"],
            solar_azimuth=solar_position["azimuth"]
        )
        cos_aoi = np.cos(np.radians(aoi))
        cos_aoi[cos_aoi < 0] = 0

        poa = ghi_kw * cos_aoi * (1 - system_losses)
        energy = float((poa * system_power_kw).sum())

        if energy > best_energy:
            best_energy = energy
            best_tilt = t

    annual_optimal_tilt = best_tilt

    # 6. User tilt energy
    aoi_user = irradiance.aoi(
        surface_tilt=user_tilt,
        surface_azimuth=180,
        solar_zenith=solar_position["apparent_zenith"],
        solar_azimuth=solar_position["azimuth"]
    )

    cos_user = np.cos(np.radians(aoi_user))
    cos_user[cos_user < 0] = 0

    poa_user = ghi_kw * cos_user * (1 - system_losses)
    hourly = poa_user * system_power_kw
    monthly_energy = hourly.resample("M").sum()
    annual_energy = float(hourly.sum())

    monthly_df = pd.DataFrame({
        "Month": monthly_energy.index.strftime("%B"),
        "Energy (kWh)": monthly_energy.values
    })

    # ---------------------------
    # 7. Plot PNG
    # ---------------------------
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(monthly_df["Month"], monthly_df["Energy (kWh)"], color="orange")
    ax.set_title(f"Monthly Energy Output (Tilt = {user_tilt:.1f}°)")
    ax.set_xlabel("Month")
    ax.set_ylabel("Energy (kWh)")
    plt.xticks(rotation=45)
    plt.tight_layout()

    tmp_plot = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    fig.savefig(tmp_plot.name, dpi=150, bbox_inches="tight")

    # ---------------------------
    # 8. Table PNG
    # ---------------------------
    table_fig, table_ax = plt.subplots(figsize=(8, 4))
    table_ax.axis("off")

    table = table_ax.table(
        cellText=monthly_df["Energy (kWh)"].round(2).values.reshape(-1, 1),
        rowLabels=monthly_df["Month"].values,
        colLabels=["Energy (kWh)"],
        loc="center",
        cellLoc="center"
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.3, 1.4)

    tmp_table = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    table_fig.savefig(tmp_table.name, dpi=150, bbox_inches="tight")

    # ---------------------------
    # 9. PDF — вирівняно!
    # ---------------------------
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
    pdf.drawString(50, y, f"User tilt: {user_tilt:.1f}°")
    y -= 18
    pdf.drawString(50, y, f"Annual optimal tilt: {annual_optimal_tilt}°")
    y -= 18
    pdf.drawString(50, y, f"Annual energy: {annual_energy:.0f} kWh")

    # 🟨 TABLE — вирівняно по центру сторінки
    table_width = 400
    table_height = 200
    x_table = (width - table_width) / 2
    y_table = y - table_height - 30

    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(50, y - 20, "Monthly Energy Table:")
    pdf.drawImage(ImageReader(tmp_table.name), x_table, y_table, width=table_width)

    # 🟧 CHART — окрема сторінка, теж центрований
    pdf.showPage()
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(50, height - 50, "Monthly Energy Chart:")

    chart_width = 500
    chart_height = 350
    x_chart = (width - chart_width) / 2
    y_chart = height - chart_height - 100

    pdf.drawImage(ImageReader(tmp_plot.name), x_chart, y_chart, width=chart_width)

    pdf.save()
    buffer.seek(0)

    # Clean temp files
    os.unlink(tmp_plot.name)
    os.unlink(tmp_table.name)

    return {
        "monthly_df": monthly_df,
        "monthly_best": monthly_best.reset_index(drop=True),
        "annual_energy": annual_energy,
        "annual_optimal_tilt": annual_optimal_tilt,
        "fig": fig,               # нове! → для Streamlit
        "pdf": buffer
    }
