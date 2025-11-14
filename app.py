import streamlit as st
from utils.base_model import calculate_solar_output
import matplotlib.pyplot as plt
import base64

st.set_page_config(page_title="Solar Advisor", layout="centered")
st.title("☀️ Solar Advisor — Базовий розрахунок")

st.markdown("""
Введіть координати вашої локації та потужність вашої СЕС для оцінки річного виробництва електроенергії.
""")

with st.form("input_form"):
    col1, col2 = st.columns(2)
    with col1:
        latitude = st.number_input("Широта (Latitude)", value=50.45, format="%.4f")
    with col2:
        longitude = st.number_input("Довгота (Longitude)", value=30.52, format="%.4f")
    
    system_power_kw = st.number_input("Потужність системи (кВт)", value=10.0, min_value=0.5, step=0.5)

    submitted = st.form_submit_button("Розрахувати")

if submitted:
    with st.spinner("Обробка даних..."):
        result = calculate_solar_output(latitude, longitude, system_power_kw)

        st.success("✅ Розрахунок завершено!")
        st.markdown(f"**Середній оптимальний кут нахилу:** `{result['avg_tilt']}°`")
        st.markdown(f"**Річна генерація:** `{result['annual_energy']} кВт·год`")

        st.markdown("### 📊 Графік генерації по місяцях")
        st.pyplot(result['fig'])

        st.markdown("### 📋 Таблиця")
        st.dataframe(result['monthly_df'])

        st.markdown("### 📄 Завантажити PDF-звіт")
        pdf = result['pdf'].getvalue()
        b64_pdf = base64.b64encode(pdf).decode('utf-8')
        href = f'<a href="data:application/octet-stream;base64,{b64_pdf}" download="solar_report.pdf">📥 Завантажити звіт (PDF)</a>'
        st.markdown(href, unsafe_allow_html=True)
