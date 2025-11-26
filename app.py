import streamlit as st
import pandas as pd

from utils.base_model import calculate_solar_output


# ------------------------------------------------------
# 🟧 Налаштування сторінки
# ------------------------------------------------------
st.set_page_config(
    page_title="Solar Ninja — Basic Model",
    page_icon="⚔️",
    layout="centered"
)

st.title("⚔️ Solar Ninja — Basic Model")
st.write("Введіть параметри нижче, щоб отримати прогноз генерації вашої сонячної системи.")


# ------------------------------------------------------
# 🟧 Форма вводу
# ------------------------------------------------------
with st.form("input_form"):
    st.subheader("Вхідні дані")

    col1, col2 = st.columns(2)
    latitude = col1.number_input("Широта (lat)", value=50.45, format="%.4f")
    longitude = col2.number_input("Довгота (lon)", value=30.52, format="%.4f")

    col3, col4 = st.columns(2)
    system_power_kw = col3.number_input("Потужність системи (кВт)", value=10.0)
    user_tilt = col4.number_input("Кут нахилу панелей (°)", value=45.0)

    submit_button = st.form_submit_button("Розрахувати")


# ------------------------------------------------------
# 🟧 Обробка результатів
# ------------------------------------------------------
if submit_button:

    st.success("Розрахунок виконано!")

    result = calculate_solar_output(
        latitude=latitude,
        longitude=longitude,
        system_power_kw=system_power_kw,
        user_tilt=user_tilt
    )

    avg_tilt = result["avg_tilt"]
    annual_energy = result["annual_energy"]
    monthly_df = result["monthly_df"]
    fig = result["fig"]
    monthly_best = result["monthly_best"]
    pdf_buffer = result["pdf"]

    # -------------------------------
    # 🔋 Річна генерація
    # -------------------------------
    st.subheader("🔋 Річна генерація")
    st.metric(
        label="Річний прогноз генерації",
        value=f"{annual_energy:,.0f} кВт·год"
    )

    # -------------------------------
    # 📅 Помісячна генерація
    # -------------------------------
    st.subheader("📅 Помісячне виробництво")
    st.dataframe(monthly_df)

    # Графік
    st.subheader("📈 Графік генерації")
    st.pyplot(fig)

    # -------------------------------
    # 📐 Оптимальні кути
    # -------------------------------
    st.subheader("📐 Оптимальний кут нахилу (аналітика)")

    st.write(
        f"**Середній оптимальний кут нахилу:** {avg_tilt:.2f}°"
    )

    st.dataframe(monthly_best.reset_index(drop=True))

    # -------------------------------
    # 📄 Завантаження PDF
    # -------------------------------
    st.subheader("📄 Завантажити PDF-звіт")

    st.download_button(
        label="Завантажити PDF",
        data=pdf_buffer,
        file_name="solar_ninja_basic_report.pdf",
        mime="application/pdf"
    )


# ------------------------------------------------------
# 🟧 Нижній опис програми
# ------------------------------------------------------
st.markdown("---")
st.markdown(
    """
    ### 🌍 Про програму  
    **Solar Ninja — Basic Model**  
    аналітичний інструмент для планування оптимальних параметрів встановлення сонячних панелей  
    в будь-якій точці світу.  
    """
)
