import streamlit as st
import requests
import pandas as pd

st.set_page_config(page_title="Aide à la Décision - Pêche au Bar V3+", layout="wide")

st.title("🎣 Aide à la Décision V3+ — Pêche au Bar")
st.caption("Zone 50km Le Croisic & Côte Sauvage | Prévisions 15J & Océanogramme SHOM")

# Coordonnées GPS et identifiants des ports
SPOTS = {
    "Côte Sauvage (Le Croisic)": {"lat": 47.2931, "lon": -2.5204, "port_id": "80"},
    "Pointe du Castelli (Piriac)": {"lat": 47.3781, "lon": -2.5512, "port_id": "80"},
    "Baie de Mesquer": {"lat": 47.3986, "lon": -2.4635, "port_id": "80"},
    "Estuaire de la Loire": {"lat": 47.2300, "lon": -2.1800, "port_id": "82"},
    "Île de Dumet": {"lat": 47.4111, "lon": -2.6208, "port_id": "80"}
}

MAREE_API_KEY = st.secrets.get("MAREE_API_KEY", "VOTRE_CLE_API_MAREE")

# 1. Sélection du spot
spot_nom = st.selectbox("Secteur de pêche", list(SPOTS.keys()))
coords = SPOTS[spot_nom]

# 2. Récupération Météo 16 jours (Open-Meteo API)
@st.cache_data(ttl=3600)
def fetch_15day_forecast(lat, lon):
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=wind_speed_10m_max,wind_direction_10m_dominant,surface_pressure_mean&forecast_days=16&timezone=auto"
    res = requests.get(url).json()
    return res.get("daily", {})

daily_data = fetch_15day_forecast(coords["lat"], coords["lon"])

# 3. Calcul des scores sur 15 jours
if daily_data:
    dates = daily_data.get("time", [])
    vitesse_vent = daily_data.get("wind_speed_10m_max", [])
    dir_vent = daily_data.get("wind_direction_10m_dominant", [])
    pression = daily_data.get("surface_pressure_mean", [])

    scores = []
    for i in range(len(dates)):
        # Calcul simplifié du score V3+ sur la tendance du jour
        is_vent_mer = 200 <= dir_vent[i] <= 290
        v_vent = 90 if (15 <= vitesse_vent[i] <= 25 and is_vent_mer) else 55
        p_press = 85 if pression[i] < 1013 else 60
        
        # Estimation baseline score quotidien
        score_jour = (0.35 * v_vent) + (0.35 * p_press) + (0.30 * 70)
        scores.append(round(score_jour, 1))

    df_scores = pd.DataFrame({
        "Date": dates,
        "Score d'Activité (/100)": scores,
        "Vent max (km/h)": vitesse_vent,
        "Pression moyenne (hPa)": pression
    }).set_index("Date")

    st.header("1. Prévision des Scores d'Activité sur 15 Jours")
    col_g, col_t = st.columns([2, 1])
    
    with col_g:
        st.line_chart(df_scores["Score d'Activité (/100)"])
    with col_t:
        st.dataframe(df_scores[["Score d'Activité (/100)", "Vent max (km/h)"]], height=280)

# 4. Vue Océanogramme SHOM
st.divider()
st.header("2. Océanogramme SHOM (Prévisions Océanographiques à 4J)")
st.caption("Données de houle, météo, mer et courants de surface directement issues du modèle SHOM / Météo-France.")

# URL de l'iframe de l'océanogramme dynamique SHOM
shom_url = f"https://services.data.shom.fr/oceano/render/html/widget?duration=4&delta-date=0&lon={coords['lon']}&lat={coords['lat']}&utc=1&lang=fr"

st.components.v1.iframe(shom_url, height=600, scrolling=True)