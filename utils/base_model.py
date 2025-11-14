import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pvlib.location import Location
from pvlib.irradiance import aoi
from io import BytesIO
from fpdf import FPDF
import calendar


def calculate_solar_output(latitude, longitude, system_power_kw=10.0):
    tz = 'Etc/GMT-0'
    times = pd.date_range('2025-01-01', '2025-12-31 23:00', freq='1h', tz=tz)
    location = Location(latitude, longitude, tz=tz)
    solar_position = location.get_solarposition(times)

    tilts = list(range(0, 91, 1))
    results = {}

    for tilt in tilts:
        current_aoi = aoi(
            surface_tilt=tilt,
            surface_azimuth=180,
            solar_zenith=solar_position['apparent_zenith'],
            solar_azimuth=solar_position['azimuth']
        )
        cos_aoi = np.cos(np.radians(current_aoi))
        cos_aoi[cos_aoi < 0] = 0
        results[f'tilt_{tilt}'] = cos_aoi

    df = pd.DataFrame(results, index=times)
    monthly_avg = df.resample('ME').mean()
    monthly_best = monthly_avg.idxmax(axis=1).str.extract(r'(\d+)').astype(int)
    monthly_best.columns = ['Best Tilt']
    avg_tilt = float(monthly_best['Best Tilt'].mean())

    # Повторний розрахунок для середнього кута
    best_aoi = aoi(
        surface_tilt=avg_tilt,
        surface_azimuth=180,
        solar_zenith=solar_position['apparent_zenith'],
        solar_azimuth=solar_position['azimuth']
    )
    cos_best = np.cos(np.radians(best_aoi))
    cos_best[cos_best < 0] = 0

    df_gen = pd.DataFrame({'cos_aoi': cos_best}, index=times)
    daily_insolation_kwh = 4.0  # усереднений показник для симуляції
    monthly_gen = df_gen.resample('M').mean() * daily_insolation_kwh * system_power_kw * 30

    monthly_gen['Month'] = monthly_gen.index.strftime('%B')
    monthly_gen['Energy (kWh)'] = monthly_gen['cos_aoi'].round(4)
    result_df = monthly_gen[['Month', 'Energy (kWh)']].copy()
    result_df.reset_index(drop=True, inplace=True)

    annual_energy = result_df['Energy (kWh)'].sum()

    # Побудова графіка
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(result_df['Month'], result_df['Energy (kWh)'], color='skyblue')
    ax.set_title('Monthly Solar Energy Output (kWh)')
    ax.set_xlabel('Month')
    ax.set_ylabel('Energy (kWh)')
    plt.xticks(rotation=45)
    plt.tight_layout()

    # Генерація PDF
    pdf_buffer = BytesIO()
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt="Solar Advisor Report", ln=1, align='C')
    pdf.cell(200, 10, txt=f"Coordinates: ({latitude}, {longitude})", ln=2)
    pdf.cell(200, 10, txt=f"System Power: {system_power_kw} kW", ln=3)
    pdf.cell(200, 10, txt=f"Average Optimal Tilt: {round(avg_tilt, 2)} degrees", ln=4)
    pdf.cell(200, 10, txt=f"Annual Generation: {round(annual_energy, 2)} kWh", ln=5)
    pdf.ln(10)

    for index, row in result_df.iterrows():
        pdf.cell(200, 8, txt=f"{row['Month']}: {round(row['Energy (kWh)'], 2)} kWh", ln=1)

    pdf.output(pdf_buffer)
    pdf_buffer.seek(0)

    return {
        'avg_tilt': round(avg_tilt, 2),
        'monthly_df': result_df,
        'annual_energy': round(annual_energy, 2),
        'fig': fig,
        'pdf': pdf_buffer
    }
