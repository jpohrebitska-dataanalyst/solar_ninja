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
from reportlab.lib.pagesizes import letter, landscape
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
    plt.close(fig)
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
    plt.close(table_fig)
    tmp_table.close()

    # ------------------------------------------------------------
    # 9. PDF (single-page summary layout)
    # ------------------------------------------------------------
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=landscape(letter))
    width, height = landscape(letter)

    # Layout helpers
    margin = 36
    content_width = width - 2 * margin
    y = height - margin

    # Header
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(margin, y, "Solar Ninja — Basic Model Report")

    # Summary block
    pdf.setFont("Helvetica", 11)
    y -= 24
    summary_lines = [
        f"Location: lat={latitude:.4f}, lon={longitude:.4f}",
        f"System power: {system_power_kw:.2f} kW",
        f"User tilt: {user_tilt:.1f}°",
        f"Annual optimal tilt: {annual_optimal_tilt}°",
        f"Annual energy: {annual_energy:.0f} kWh",
    ]

    for line in summary_lines:
        pdf.drawString(margin, y, line)
        y -= 16

    # Titles for main content
    y -= 6
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(margin, y, "Monthly Energy Table")
    pdf.drawString(margin + content_width / 2, y, "Monthly Energy Chart")
    y -= 14

    # Column layout sizes
    col_width = content_width / 2 - 10
    available_height = y - margin

    # Load assets
    table_img = ImageReader(tmp_table.name)
    table_w, table_h = table_img.getSize()
    chart_img = ImageReader(tmp_plot.name)
    chart_w, chart_h = chart_img.getSize()

    # Scale to fit columns while preserving aspect ratio
    table_scale = min(col_width / table_w, available_height / table_h, 1.0)
    chart_scale = min(col_width / chart_w, available_height / chart_h, 1.0)

    new_tw = table_w * table_scale
    new_th = table_h * table_scale
    new_cw = chart_w * chart_scale
    new_ch = chart_h * chart_scale

    # Vertical centering within available height
    table_y = margin + (available_height - new_th) / 2
    chart_y = margin + (available_height - new_ch) / 2

    # Draw images side by side
    pdf.drawImage(
        table_img,
        margin,
        table_y,
        width=new_tw,
        height=new_th,
        preserveAspectRatio=True,
        anchor="sw",
    )

    pdf.drawImage(
        chart_img,
        margin + col_width + 20,
        chart_y,
        width=new_cw,
        height=new_ch,
        preserveAspectRatio=True,
        anchor="sw",
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
