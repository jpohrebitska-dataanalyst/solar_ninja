import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

from pvlib.location import Location
from pvlib import irradiance
from io import BytesIO
from fpdf import FPDF


def calculate_solar_output(latitude: float,
                           longitude: float,
                           system_power_kw: float,
                           user_tilt: float) -> dict:
    """
    Фізична модель Solar Advisor для прогнозу генерації (Модель B).

    Генерація = GHI × cos(AOI) × (1 - losses) × Power

    ДЕ:
    - GHI — глобальна горизонтальна радіація (Вт/м²)
    - AOI — кут падіння променів на панель
    - (1 - losses) — коефіцієнт системних втрат
    - Power — потужність системи (кВт)

    Повертає:
    - помісячну генерацію
    - річну генерацію
    - оптимальні кути помісячно
    - середній оптимальний кут
    - PDF-звіт
    """

    # ------------------------------------------------------
    # 1. Погодинна шкала на весь рік
    # ------------------------------------------------------
    timezone = "UTC"
    times = pd.date_range(
        "2025-01-01", "2025-12-31 23:00",
        freq="1h", tz=timezone
    )

    # ------------------------------------------------------
    # 2. Локація
    # ------------------------------------------------------
    location = Location(
        latitude=latitude,
        longitude=longitude,
        tz=timezone
    )

    # ------------------------------------------------------
    # 3. Сонячна позиція
    # ------------------------------------------------------
    solar_position = location.get_solarposition(times)

    # ------------------------------------------------------
    # 4. Модель ясного неба (GHI/DNI/DHI)
    # ------------------------------------------------------
    clear_sky = location.get_clearsky(times, model="ineichen")

    ghi = clear_sky["ghi"]
    dni = clear_sky["dni"]
    dhi = clear_sky["dhi"]

    # ------------------------------------------------------
    # 5. АНАЛІТИКА: оптимальний кут помісячно
    # ------------------------------------------------------
    tilts = list(range(0, 91))
    cos_results = {}

    for tilt in tilts:
        aoi = irradiance.aoi(
            surface_tilt=tilt,
            surface_azimuth=180,  # 180° = південь
            solar_zenith=solar_position["apparent_zenith"],
            solar_azimuth=solar_position["azimuth"]
        )

        cos_aoi = np.cos(np.radians(aoi))
        cos_aoi[cos_aoi < 0] = 0   # ніч і негативні значення → 0

        cos_results[f"tilt_{tilt}"] = cos_aoi

    df_cos = pd.DataFrame(cos_results, index=times)

    monthly_avg = df_cos.resample("M").mean()

    monthly_best = monthly_avg.idxmax(axis=1).str.extract(r"(\d+)").astype(int)
    monthly_best.columns = ["Best Tilt"]
    monthly_best["Month"] = monthly_best.index.strftime("%B")

    avg_optimal_tilt = float(monthly_best["Best Tilt"].mean())

    # ------------------------------------------------------
    # 6. ОСНОВНА МОДЕЛЬ — генерація за user_tilt
    # ------------------------------------------------------

    # 6.1 AOI для введеного кута
    aoi_user = irradiance.aoi(
        surface_tilt=user_tilt,
        surface_azimuth=180,
        solar_zenith=solar_position["apparent_zenith"],
        solar_azimuth=solar_position["azimuth"]
    )

    # 6.2 cos(AOI), негативні значення = 0
    cos_aoi_user = np.cos(np.radians(aoi_user))
    cos_aoi_user[cos_aoi_user < 0] = 0

    # 6.3 Ефективна інсоляція (GHI × cosAOI)
    poa_effective = ghi * cos_aoi_user

    # 6.4 Застосовуємо системні втрати
    system_losses = 0.20   # 20% втрат — реалістично
    poa_effective = poa_effective * (1 - system_losses)

    # 6.5 Перехід у кВт·год
    energy_hourly_kw = (poa_effective / 1000.0) * system_power_kw

    df_energy = pd.DataFrame({"energy": energy_hourly_kw}, index=times)

    # 6.6 Помісячна генерація
    monthly_energy = df_energy.resample("M").sum()
    monthly_energy["Month"] = monthly_energy.index.strftime("%B")

    result_df = monthly_energy[["Month", "energy"]].copy()
    result_df.rename(columns={"energy": "Energy (kWh)"}, inplace=True)
    result_df.reset_index(drop=True, inplace=True)

    annual_energy = float(result_df["Energy (kWh)"].sum())

    # ------------------------------------------------------
    # 7. ГРАФІК
    # ------------------------------------------------------
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(result_df["Month"], result_df["Energy (kWh)"], color="orange")
    ax.set_title(f"Monthly Solar Energy Output (Tilt = {user_tilt}°)")
    ax.set_xlabel("Month")
    ax.set_ylabel("Energy (kWh)")
    plt.xticks(rotation=45)
    plt.tight_layout()

    # ------------------------------------------------------
    # 8. PDF
    # ------------------------------------------------------
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    pdf.cell(200, 10, "Solar Advisor Report", ln=1, align="C")
    pdf.cell(200, 10, f"Coordinates: ({round(latitude,3)}, {round(longitude,3)})", ln=2)
    pdf.cell(200, 10, f"System Power: {system_power_kw} kW", ln=3)
    pdf.cell(200, 10, f"User Tilt: {user_tilt}°", ln=4)
    pdf.cell(200, 10, f"Average Optimal Tilt: {round(avg_optimal_tilt,2)}°", ln=5)
    pdf.cell(200, 10, f"Annual Generation: {round(annual_energy,2)} kWh", ln=6)
    pdf.ln(10)

    pdf.cell(200, 10, "Monthly Energy (kWh):", ln=1)
    for _, row in result_df.iterrows():
        pdf.cell(200, 8, f"{row['Month']}: {round(row['Energy (kWh)'],2)}", ln=1)

    pdf_bytes = pdf.output(dest="S").encode("latin1")
    pdf_buffer = BytesIO(pdf_bytes)
    pdf_buffer.seek(0)

    return {
        "avg_tilt": round(avg_optimal_tilt, 2),
        "monthly_df": result_df,
        "annual_energy": round(annual_energy, 2),
        "fig": fig,
        "monthly_best": monthly_best,
        "pdf": pdf_buffer
    }
