import streamlit as st
from utils.base_model import calculate_solar_output


st.set_page_config(
    page_title="Solar Ninja — Basic Model",
    page_icon="⚔️",
    layout="centered"
)

st.title("⚔️ Solar Ninja — Basic Model")
st.write("Enter the location and solar system parameters to estimate monthly and annual energy output.")

with st.form("input_form"):
    st.subheader("Input parameters")

    col1, col2 = st.columns(2)
    latitude = col1.number_input("Latitude (deg)", value=50.45, format="%.4f")
    longitude = col2.number_input("Longitude (deg)", value=30.52, format="%.4f")

    col3, col4 = st.columns(2)
    system_power_kw = col3.number_input("System power (kW)", value=10.0)
    user_tilt = col4.number_input("Panel tilt (deg)", value=45.0)

    submitted = st.form_submit_button("Calculate")

if submitted:
    with st.spinner("Running Solar Ninja calculations..."):
        result = calculate_solar_output(
            latitude=latitude,
            longitude=longitude,
            system_power_kw=system_power_kw,
            user_tilt=user_tilt
        )

    st.success("Calculation completed.")

    monthly_df = result["monthly_df"]
    monthly_best = result["monthly_best"]
    annual_energy = result["annual_energy"]
    annual_optimal_tilt = result["annual_optimal_tilt"]
    pdf_buffer = result["pdf"]

    # ---------------------------
    # Streamlit графік (нова секція)
    # ---------------------------
    st.subheader("Monthly Energy Chart")
    st.pyplot(result["fig"])

    # Annual summary
    st.subheader("Annual summary")
    colA, colB = st.columns(2)
    colA.metric("Annual energy (user tilt)", f"{annual_energy:,.0f} kWh")
    colB.metric("Annual optimal tilt", f"{annual_optimal_tilt}°")

    # Monthly tables
    st.subheader("Monthly energy (user tilt)")
    st.dataframe(monthly_df)

    st.subheader("Monthly optimal tilts (analytics)")
    st.dataframe(monthly_best)

    # PDF download
    st.subheader("Download report")
    st.download_button(
        label="Download PDF",
        data=pdf_buffer,
        file_name="solar_ninja_basic_report.pdf",
        mime="application/pdf"
    )

st.markdown("---")
st.markdown(
    """
    ### About  
    **Solar Ninja — Basic Model** is an analytical tool for estimating  
    solar power generation for any location in the world.
    """
)
