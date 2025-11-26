import pandas as pd
import numpy as np
from pvlib.location import Location
import pvlib
from pvlib import irradiance, atmosphere
from fpdf import FPDF
import matplotlib.pyplot as plt
from io import BytesIO


def calculate_solar_output(latitude, longitude, system_power_kw, user_tilt):
    """
    Основна функція:
    - розрахунок сонячного положення
    - розрахунок GHI
    - розрахунок генерації за user tilt
    - визначення monthly optimal tilts
    - визначення annual optimal tilt (НОВЕ)
    """

    # ------------------------------------------------------------
    # 1. Генеруємо погодинну часову шкалу
    # ------------------------------------------------------------
    times = pd.date_range(
        '2025-01-01', '2025-12-31 23:00',
        freq='1h',
        tz='UTC'
    )

    location = Location(latitude=latitude, longitude=longitude, tz='UTC')

    # Положення сонця
    solar_position = location.get_solarposition(times)

    # ------------------------------------------------------------
    # 2. GHI через модель Дарі
    # ------------------------------------------------------------
    ghi = irradiance.haurwitz(solar_position["apparent_zenith"])
    ghi[ghi < 0] = 0

    # ------------------------------------------------------------
    # 3. Розрахунок помісячних оптимальних кутів
    # ------------------------------------------------------------
    tilts = list(range(0, 91))
    monthly_aoi_dict = {}

    for tilt in tilts:
        aoi = irradiance.aoi(
            surface_tilt=tilt,
            surface_azimuth=180,
            solar_zenith=solar_position["apparent_zenith"],
            solar_azimuth=solar_position["azimuth"]
        )
        cos_aoi = np.cos(np.radians(aoi))
        cos_aoi[cos_aoi < 0] = 0

        monthly_aoi_dict[f"tilt_{tilt}"] = cos_aoi

    df_aoi = pd.DataFrame(monthly_aoi_dict, index=times)

    monthly_avg = df_aoi.resample("ME").mean()
    monthly_best = monthly_avg.idxmax(axis=1).str.extract(r"(\d+)").astype(int)
    monthly_best.columns = ["Best Tilt"]
    monthly_best["Month"] = monthly_best.index.strftime("%B")

    # ------------------------------------------------------------
    # 4. Розрахунок річного оптимального кута (НОВА ЛОГІКА)
    # ------------------------------------------------------------

    system_losses = 0.20  # базові втрати
    ghi_kw = ghi / 1000.0  # перевід W/m2 → kW/m2

    best_annual_tilt = None
    best_annual_energy = -1

    for tilt in tilts:
        aoi = irradiance.aoi(
            surface_tilt=tilt,
            surface_azimuth=180,
            solar_zenith=solar_position["apparent_zenith"],
            solar_azimuth=solar_position["azimuth"]
        )

        cos_aoi = np.cos(np.radians(aoi))
        cos_aoi[cos_aoi < 0] = 0

        poa_effective = ghi_kw * cos_aoi
        poa_effective = poa_effective * (1 - system_losses)

        hourly_energy = poa_effective * system_power_kw
        annual_energy = hourly_energy.sum()

        if annual_energy > best_annual_energy:
            best_annual_energy = annual_energy
            best_annual_tilt = tilt

    annual_optimal_tilt = best_annual_tilt

    # ------------------------------------------------------------
    # 5. Генерація за user tilt
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
    poa_user = poa_user * (1 - system_losses)

    hourly_energy_user = poa_user * system_power_kw
    monthly_energy = hourly_energy_user.resample("ME").sum()
    annual_energy_user = hourly_energy_user.sum()

    monthly_df = pd.DataFrame({
        "Month": monthly_energy.index.strftime("%B"),
        "Energy (kWh)": monthly_energy.values
    })

    # ------------------------------------------------------------
    # 6. Графік генерації
    # ------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(monthly_df["Month"], monthly_df["Energy (kWh)"], marker="o")
    ax.set_title("Помісячна генерація (кВт·год)")
    ax.set_ylabel("kWh")
    ax.set_xlabel("Місяць")
    plt.xticks(rotation=45)
    plt.tight_layout()

    # ------------------------------------------------------------
    # 7. PDF
    # ------------------------------------------------------------
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=14)
    pdf.cell(200, 10, txt="Solar Ninja — Basic Model", ln=True, align="C")
    pdf.ln(5)

    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"Location: lat={latitude}, lon={longitude}", ln=True)
    pdf.cell(200, 10, txt=f"System Power: {system_power_kw} kW", ln=True)
    pdf.cell(200, 10, txt=f"User Tilt: {user_tilt}°", ln=True)
    pdf.cell(200, 10, txt=f"Annual Optimal Tilt: {annual_optimal_tilt}°", ln=True)
    pdf.cell(200, 10, txt=f"Annual Energy: {annual_energy_user:.0f} kWh", ln=True)

    pdf_buffer = BytesIO()
    pdf.output(pdf_buffer)
    pdf_buffer.seek(0)

    # ------------------------------------------------------------
    # 8. Повертаємо все
    # ------------------------------------------------------------
    return {
        "monthly_df": monthly_df,
        "monthly_best": monthly_best,
        "annual_energy": annual_energy_user,
        "annual_optimal_tilt": annual_optimal_tilt,
        "fig": fig,
        "pdf": pdf_buffer
    }
