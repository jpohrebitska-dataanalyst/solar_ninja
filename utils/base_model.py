import pandas as pd
import numpy as np
from pvlib.location import Location
from pvlib import irradiance
from fpdf import FPDF
import matplotlib.pyplot as plt
from io import BytesIO
import tempfile
import os


def calculate_solar_output(latitude, longitude, system_power_kw, user_tilt):
    """
    Solar Ninja — Basic Model

    Core logic:
    - clear-sky GHI (Ineichen model)
    - AOI-based adjustment with cos(AOI), zero at night
    - system losses (constant factor)
    - monthly and annual energy for user-defined tilt
    - monthly optimal tilt (by average cos(AOI))
    - annual optimal tilt (tilt with max annual energy)
    - PDF report with:
        - text summary
        - monthly table (as PNG)
        - energy chart (as PNG)
    """

    # ------------------------------------------------------------
    # 1. Time index for the whole year (hourly)
    # ------------------------------------------------------------
    timezone = "UTC"
    times = pd.date_range(
        "2025-01-01", "2025-12-31 23:00",
        freq="1h",
        tz=timezone
    )

    # ------------------------------------------------------------
    # 2. Location and solar position
    # ------------------------------------------------------------
    location = Location(latitude=latitude, longitude=longitude, tz=timezone)
    solar_position = location.get_solarposition(times)

    # ------------------------------------------------------------
    # 3. Clear-sky GHI with Ineichen model
    # ------------------------------------------------------------
    clearsky = location.get_clearsky(times, model="ineichen")
    ghi = clearsky["ghi"].copy()
    ghi[ghi < 0] = 0  # safety

    # Convert to kW/m²
    ghi_kw = ghi / 1000.0

    # ------------------------------------------------------------
    # 4. Monthly optimal tilts (analytic, per month)
    #    We find, for each month, the tilt with maximum average cos(AOI).
    # ------------------------------------------------------------
    tilts = list(range(0, 91))
    monthly_cos_dict = {}

    for tilt in tilts:
        aoi = irradiance.aoi(
            surface_tilt=tilt,
            surface_azimuth=180,  # facing South
            solar_zenith=solar_position["apparent_zenith"],
            solar_azimuth=solar_position["azimuth"]
        )

        cos_aoi = np.cos(np.radians(aoi))
        cos_aoi[cos_aoi < 0] = 0  # night and negative incidence → 0

        monthly_cos_dict[f"tilt_{tilt}"] = cos_aoi

    df_cos = pd.DataFrame(monthly_cos_dict, index=times)

    # Monthly mean cos(AOI) per tilt
    monthly_avg = df_cos.resample("M").mean()

    # For each month, choose tilt with max average cos(AOI)
    monthly_best = monthly_avg.idxmax(axis=1).str.extract(r"(\d+)").astype(int)
    monthly_best.columns = ["Best Tilt (deg)"]
    monthly_best["Month"] = monthly_best.index.strftime("%B")

    # ------------------------------------------------------------
    # 5. Annual optimal tilt (tilt with max annual energy)
    # ------------------------------------------------------------
    system_losses = 0.20  # 20% system losses

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
        poa = poa * (1.0 - system_losses)

        hourly_energy = poa * system_power_kw  # kWh per hour
        annual_energy = float(hourly_energy.sum())

        if annual_energy > best_annual_energy:
            best_annual_energy = annual_energy
            best_annual_tilt = tilt

    annual_optimal_tilt = best_annual_tilt

    # ------------------------------------------------------------
    # 6. Energy calculation for user-defined tilt
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
    poa_user = poa_user * (1.0 - system_losses)

    hourly_energy_user = poa_user * system_power_kw  # kWh per hour

    # Monthly energy (end-of-month)
    monthly_energy = hourly_energy_user.resample("M").sum()
    annual_energy_user = float(hourly_energy_user.sum())

    monthly_df = pd.DataFrame({
        "Month": monthly_energy.index.strftime("%B"),
        "Energy (kWh)": monthly_energy.values
    })

    # ------------------------------------------------------------
    # 7. Plot: Monthly energy chart (for Streamlit + PDF)
    # ------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(monthly_df["Month"], monthly_df["Energy (kWh)"], color="orange")
    ax.set_title(f"Monthly Energy Output (Tilt = {user_tilt:.1f}°)")
    ax.set_xlabel("Month")
    ax.set_ylabel("Energy (kWh)")
    plt.xticks(rotation=45)
    plt.tight_layout()

    # Save chart to a temporary PNG file for PDF
    plot_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    fig.savefig(plot_tmp.name, dpi=150, bbox_inches="tight")
    plt.close(fig)  # close figure to free memory

    # ------------------------------------------------------------
    # 8. Table figure (Tableau-style) as PNG
    # ------------------------------------------------------------
    table_fig, table_ax = plt.subplots(figsize=(8, 4))
    table_ax.axis("off")

    table = table_ax.table(
        cellText=np.round(monthly_df["Energy (kWh)"].values, 2).reshape(-1, 1),
        rowLabels=monthly_df["Month"].values,
        colLabels=["Energy (kWh)"],
        cellLoc="center",
        loc="center"
    )

    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.2, 1.4)

    # Style header row
    for (row, col), cell in table.get_celld().items():
        if row == 0:
            cell.set_text_props(weight="bold")
            cell.set_facecolor("#E5E5E5")
        else:
            cell.set_facecolor("#FFFFFF")

    table_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    table_fig.savefig(table_tmp.name, dpi=150, bbox_inches="tight")
    plt.close(table_fig)

    # ------------------------------------------------------------
    # 9. Build PDF report (all English, ASCII-safe)
    # ------------------------------------------------------------
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=14)

    pdf.cell(200, 10, "Solar Ninja — Basic Model Report", ln=True, align="C")
    pdf.ln(5)

    pdf.set_font("Arial", size=11)
    pdf.cell(200, 8, f"Location: lat={latitude:.4f}, lon={longitude:.4f}", ln=True)
    pdf.cell(200, 8, f"System power: {system_power_kw:.2f} kW", ln=True)
    pdf.cell(200, 8, f"User tilt: {user_tilt:.1f} deg", ln=True)
    pdf.cell(200, 8, f"Annual optimal tilt: {annual_optimal_tilt} deg", ln=True)
    pdf.cell(200, 8, f"Annual energy (user tilt): {annual_energy_user:.0f} kWh", ln=True)

    pdf.ln(8)
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 8, "Monthly energy table:", ln=True)

    # Insert table image
    pdf.ln(2)
    pdf.image(table_tmp.name, x=10, y=None, w=180)

    # New page for chart
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 8, "Monthly energy chart:", ln=True)
    pdf.ln(2)
    pdf.image(plot_tmp.name, x=10, y=None, w=180)

    # Convert PDF to bytes
    pdf_bytes = pdf.output(dest="S").encode("latin1")
    pdf_buffer = BytesIO(pdf_bytes)
    pdf_buffer.seek(0)

    # Clean up temp files
    try:
        os.unlink(plot_tmp.name)
        os.unlink(table_tmp.name)
    except Exception:
        pass

    # ------------------------------------------------------------
    # 10. Return results for Streamlit app
    # ------------------------------------------------------------
    return {
        "monthly_df": monthly_df,
        "monthly_best": monthly_best.reset_index(drop=True),
        "annual_energy": round(annual_energy_user, 2),
        "annual_optimal_tilt": annual_optimal_tilt,
        "fig": None,  # we already saved and closed the figure; Streamlit can use data if needed
        "pdf": pdf_buffer,
    }
