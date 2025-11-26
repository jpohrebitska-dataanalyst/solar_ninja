import pandas as pd
import numpy as np
from pvlib.location import Location
from pvlib import irradiance
import matplotlib.pyplot as plt
from io import BytesIO
import tempfile
import os

# ReportLab PDF
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader


def calculate_solar_output(latitude, longitude, system_power_kw, user_tilt):
    """
    Solar Ninja — Basic Model
    """

    # ------------------------------------------------------------
    # 1. Time index
    # ------------------------------------------------------------
    timezone = "UTC"
    times = pd.date_range(
        "2025-01-01", "2025-12-31 23:00",
        freq="1h",
        tz=timezone
    )

    # ------------------------------------------------------------
    # 2. Location & sun positions
    # ------------------------------------------------------------
    location = Location(latitude=latitude, longitude=longitude, tz=timezone)
    solar_position = location.get_solarposition(times)

    # ------------------------------------------------------------
    # 3. Clearsky GHI
    # ------------------------------------------------------------
    clearsky = location.get_clearsky(times, model="ineichen")
    ghi = clearsky["ghi"].clip(lower=0)
    ghi_kw = ghi / 1000.0

    # ------------------------------------------------------------
    # 4. Monthly optimal tilt
    # ------------------------------------------------------------
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

    # ------------------------------------------------------------
    # 5. Annual optimal tilt
    # ------------------------------------------------------------
    system_losses = 0.20
    best_tilt = None
    best_energy = -1.0

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

    # ------------------------------------------------------------
    # 6. User tilt energy
    # ------------------------------------------------------------
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

    # ------------------------------------------------------------
    # 7. PNG: Monthly Chart (fixed size)
    # ------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(8, 4), dpi=150)
    ax.bar(monthly_df["Month"], monthly_df["Energy (kWh)"], color="orange")
    ax.set_title(f"Monthly Energy Output (Tilt = {user_tilt:.1f}°)")
    ax.set_xlabel("Month")
    ax.set_ylabel("Energy (kWh)")
    plt.xticks(rotation=45)
    plt.tight_layout()

    tmp_plot = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    fig.savefig(tmp_plot.name, dpi=150)
    tmp_plot.close()

    # ------------------------------------------------------------
    # 8. PNG: Table (fixed size)
    # ------------------------------------------------------------
    table_fig, table_ax = plt.subplots(figsize=(6, 3), dpi=150)
    table_ax.axis("off")

    table = table_ax.table(
        cellText=monthly_df["Energy (kWh)"].round(2).values.reshape(-1, 1),
        rowLabels=monthly_df["Month"].values,
        colLabels=["Energy (kWh)"],
        loc="center",
        cellLoc="center"
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.3, 1.3)

    tmp_table = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    table_fig.savefig(tmp_table.name, dpi=150)
    tmp_table.close()

    # ------------------------------------------------------------
    # 9. PDF (ideal alignment)
    # ------------------------------------------------------------
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # Header
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

    # ------------------------------------------------------------
    # Insert TABLE (centered and aligned)
    # ------------------------------------------------------------
    pdf.setFont("Helvetica-Bold", 13)
    y -= 40
    pdf.drawString(50, y, "Monthly Energy Table:")
    y -= 20

    # Load PNG and fit to page
    table_img = ImageReader(tmp_table.name)
    table_w, table_h = table_img.getSize()

    margin = 50
    content_width = width - 2 * margin
    available_height = y - margin

    scale_factor = min(content_width / table_w, available_height / table_h, 1.0)
    new_w = table_w * scale_factor
    new_h = table_h * scale_factor

    x_pos = margin + (content_width - new_w) / 2
    y_pos = y - new_h

    pdf.drawImage(
        table_img,
        x_pos,
        y_pos,
        width=new_w,
        height=new_h,
        preserveAspectRatio=True,
        anchor="c",
    )

    y = y_pos - 30

    # ------------------------------------------------------------
    # NEW PAGE + CHART (centered and aligned)
    # ------------------------------------------------------------
    pdf.showPage()
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(50, height - 50, "Monthly Energy Chart:")

    chart_img = ImageReader(tmp_plot.name)
    chart_w, chart_h = chart_img.getSize()

    chart_available_height = height - 2 * margin
    scale_chart = min((content_width) / chart_w, chart_available_height / chart_h, 1.0)

    new_cw = chart_w * scale_chart
    new_ch = chart_h * scale_chart

    x_chart = margin + (content_width - new_cw) / 2
    y_chart = margin + (chart_available_height - new_ch)

    pdf.drawImage(
        chart_img,
        x_chart,
        y_chart,
        width=new_cw,
        height=new_ch,
        preserveAspectRatio=True,
        anchor="c",
    )

    pdf.save()
    buffer.seek(0)

    # Clean temp files
    os.unlink(tmp_plot.name)
    os.unlink(tmp_table.name)

    # ------------------------------------------------------------
    # Return
    # ------------------------------------------------------------
    return {
        "monthly_df": monthly_df,
        "monthly_best": monthly_best.reset_index(drop=True),
        "annual_energy": annual_energy,
        "annual_optimal_tilt": annual_optimal_tilt,
        "fig": fig,
        "pdf": buffer
    }
