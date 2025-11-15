import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

from pvlib.location import Location
from pvlib import irradiance, clearsky
from io import BytesIO
from fpdf import FPDF


def calculate_solar_output(latitude: float,
                           longitude: float,
                           system_power_kw: float = 10.0) -> dict:
    """
    Базова модель Solar Advisor (PVWatts-style).

    Ідея:
    - Ми моделюємо, скільки енергії за рік виробить СЕС потужністю 1 кВт (kWh/kWp),
      а потім просто множимо на потужність системи користувача (system_power_kw).
    - Уся фізика (сонячна радіація, геометрія, втрати) «зашита» всередині моделі.
      Користувач працює тільки з кВт.

    Параметри
    ---------
    latitude : float
        Географічна широта локації (в градусах, + на пн).
    longitude : float
        Географічна довгота локації (в градусах, + на схід).
    system_power_kw : float
        Встановлена DC-потужність системи (кВт).

    Повертає
    --------
    dict з ключами:
        - 'avg_tilt' : оптимальний річний кут нахилу (градуси)
        - 'monthly_df' : DataFrame з місяцями та кВт·год
        - 'annual_energy' : річна генерація (кВт·год)
        - 'fig' : matplotlib.figure.Figure з графіком
        - 'pdf' : BytesIO з PDF-звітом
    """

    # 1. Створюємо часову шкалу: весь 2025 рік, крок 1 година, в часовій зоні UTC.
    #    Для річних/місячних сум прив’язка до конкретного TZ не критична,
    #    головне — консистентність.
    tz = "UTC"
    times = pd.date_range(
        "2025-01-01", "2025-12-31 23:00",
        freq="1h", tz=tz
    )

    # 2. Опис локації для pvlib
    location = Location(latitude=latitude,
                        longitude=longitude,
                        tz=tz)

    # 3. Положення Сонця для кожної години
    solar_position = location.get_solarposition(times)

    # 4. Clear-sky модель (Ineichen) — дає GHI/DNI/DHI для ясного неба.
    #    Це фізично коректна модель для будь-якої точки світу,
    #    не зав’язана на якусь конкретну широту.
    cs = location.get_clearsky(times, model="ineichen")
    ghi = cs["ghi"]
    dni = cs["dni"]
    dhi = cs["dhi"]

    # 5. Підбір оптимального фіксованого кута нахилу панелей (0–90°).
    #    Для кожного кута рахуємо річну суму опромінення на площині панелі
    #    й обираємо кут з максимальною енергією.
    tilts = list(range(0, 91))
    annual_poa_per_tilt = []

    for tilt in tilts:
        poa = irradiance.get_total_irradiance(
            surface_tilt=tilt,
            surface_azimuth=180,  # 180° = південь у pvlib
            dni=dni,
            ghi=ghi,
            dhi=dhi,
            solar_zenith=solar_position["apparent_zenith"],
            solar_azimuth=solar_position["azimuth"]
        )
        # poa_global — сумарне опромінення на площині панелі (Вт/м²)
        annual_poa = poa["poa_global"].sum()
        annual_poa_per_tilt.append(annual_poa)

    # Індекс кута, який дає максимальну річну POA-енергію
    best_index = int(np.argmax(annual_poa_per_tilt))
    optimal_tilt = tilts[best_index]

    # 6. Обчислюємо POA (опромінення на площині) вже для оптимального кута
    poa_opt = irradiance.get_total_irradiance(
        surface_tilt=optimal_tilt,
        surface_azimuth=180,
        dni=dni,
        ghi=ghi,
        dhi=dhi,
        solar_zenith=solar_position["apparent_zenith"],
        solar_azimuth=solar_position["azimuth"]
    )

    # 7. PVWatts-style модель для 1 кВт (1 kWp).
    #
    #   Ідея PVWatts:
    #   P_dc (кВт) ≈ G_poa / 1000 * P_dc0  (P_dc0 = 1 кВт для кВт/kWp)
    #   P_ac (кВт) ≈ P_dc * (1 - system_losses)
    #
    #   Ми не просимо користувача вводити ефективність/площу модулів.
    #   Замість цього припускаємо усереднені втрати системи (кабелі, інвертор, температура тощо).
    system_losses = 0.14  # 14% втрат — типовий параметр в PVWatts

    # poa_global [Вт/м²] → ділимо на 1000, отримуємо кВт/м².
    # Для 1 kWp вважаємо, що площею/ефективністю вже "поглинуто" в цю нормалізацію.
    ac_per_kwp_hourly = poa_opt["poa_global"] / 1000.0 * (1 - system_losses)

    # Структуруємо в DataFrame для зручної агрегації
    df_hourly = pd.DataFrame({"ac_per_kwp": ac_per_kwp_hourly}, index=times)

    # 8. Помісячні суми (kWh/kWp на місяць)
    monthly_specific = df_hourly.resample("M").sum()  # kWh/kWp per month
    monthly_specific["Month"] = monthly_specific.index.strftime("%B")

    # 9. Перерахунок на реальну систему користувача:
    #    Енергія системи = (kWh/kWp) × (kWp системи)
    monthly_specific["Energy (kWh)"] = monthly_specific["ac_per_kwp"] * system_power_kw

    # Для повернення — залишаємо тільки місяць + енергію
    result_df = monthly_specific[["Month", "Energy (kWh)"]].copy()
    result_df.reset_index(drop=True, inplace=True)

    annual_energy = float(result_df["Energy (kWh)"].sum())
    avg_tilt = float(optimal_tilt)

    # 10. Побудова графіка (bar chart по місяцях)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(result_df["Month"], result_df["Energy (kWh)"], color="skyblue")
    ax.set_title("Monthly Solar Energy Output (kWh)")
    ax.set_xlabel("Month")
    ax.set_ylabel("Energy (kWh)")
    plt.xticks(rotation=45)
    plt.tight_layout()

    # 11. Формування PDF-звіту (текст + табличка)
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    pdf.cell(200, 10, txt="Solar Advisor Report", ln=1, align="C")
    pdf.cell(200, 10, txt=f"Coordinates: ({round(latitude, 4)}, {round(longitude, 4)})", ln=2)
    pdf.cell(200, 10, txt=f"System Power: {system_power_kw} kW", ln=3)
    pdf.cell(200, 10, txt=f"Optimal Fixed Tilt: {avg_tilt} degrees", ln=4)
    pdf.cell(200, 10, txt=f"Annual Generation: {round(annual_energy, 2)} kWh", ln=5)
    pdf.ln(10)

    pdf.cell(200, 10, txt="Monthly Energy (kWh):", ln=1)
    for _, row in result_df.iterrows():
        month = row["Month"]
        energy = round(row["Energy (kWh)"], 2)
        pdf.cell(200, 8, txt=f"{month}: {energy} kWh", ln=1)

    # Отримуємо PDF як байти (без збереження у файл)
    pdf_bytes = pdf.output(dest="S").encode("latin1")
    pdf_buffer = BytesIO(pdf_bytes)
    pdf_buffer.seek(0)

    return {
        "avg_tilt": round(avg_tilt, 2),
        "monthly_df": result_df,
        "annual_energy": round(annual_energy, 2),
        "fig": fig,
        "pdf": pdf_buffer,
    }
