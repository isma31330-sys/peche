import streamlit as st
import requests
from datetime import datetime

st.set_page_config(page_title="Aide à la Décision - Pêche au Bar V3+", layout="centered")

st.title("🎣 Aide à la Décision V3+ — Pêche au Bar")
st.caption("Zone 50km Le Croisic & Côte Sauvage | Météo & Marée Temps Réel")

# Mapping des spots avec coordonnées GPS et identifiant de port maree.info (Le Croisic / St-Nazaire / Piriac)
SPOTS = {
    "Côte Sauvage (Le Croisic)": {"lat": 47.2931, "lon": -2.5204, "port_id": "80"},     # Le Croisic
    "Pointe du Castelli (Piriac)": {"lat": 47.3781, "lon": -2.5512, "port_id": "80"},   # Le Croisic
    "Baie de Mesquer": {"lat": 47.3986, "lon": -2.4635, "port_id": "80"},           # Le Croisic
    "Estuaire de la Loire": {"lat": 47.2300, "lon": -2.1800, "port_id": "82"},      # St-Nazaire
    "Île de Dumet": {"lat": 47.4111, "lon": -2.6208, "port_id": "80"}              # Le Croisic
}

# Clé API maree.info (à configurer dans les Secrets Streamlit ou à coller ici)
MAREE_API_KEY = st.secrets.get("MAREE_API_KEY", "VOTRE_CLE_API_MAREE")

# 1. Sélection du Spot et du Créneau
st.header("1. Localisation & Moment")
col1, col2 = st.columns(2)

with col1:
    spot_nom = st.selectbox("Secteur de pêche", list(SPOTS.keys()))
    coords = SPOTS[spot_nom]

with col2:
    moment = st.selectbox(
        "Moment du jour",
        ["Aube (Coup du matin)", "Matin (Lumière douce)", "Après-Midi (Plein soleil)", "Crépuscule (Coup du soir)", "Nuit"]
    )

# 2. Récupération Météo (Open-Meteo)
@st.cache_data(ttl=1800)
def fetch_weather_data(lat, lon):
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=surface_pressure,wind_speed_10m,wind_direction_10m&hourly=surface_pressure&forecast_days=1"
    res = requests.get(url).json()
    current = res.get("current", {})
    hourly = res.get("hourly", {})
    
    pression = current.get("surface_pressure", 1013.25)
    vent_vitesse = current.get("wind_speed_10m", 15.0)
    vent_dir = current.get("wind_direction_10m", 270)
    
    pressions_hourly = hourly.get("surface_pressure", [])
    delta_p = (pressions_hourly[3] - pressions_hourly[0]) if len(pressions_hourly) >= 4 else 0.0
    return pression, vent_vitesse, vent_dir, delta_p

# 3. Récupération Marée (api.maree.info)
@st.cache_data(ttl=3600)
def fetch_tide_data(port_id, api_key):
    url = f"http://api.maree.info/m/tide/{port_id}?token={api_key}"
    try:
        res = requests.get(url, timeout=5).json()
        # Extraction du coefficient du jour et des horaires
        coef = int(res["tide"][0]["coef"]) if "tide" in res and res["tide"] else 75
        return coef, "Données live maree.info"
    except Exception:
        # Fallback si clé invalide ou API indisponible
        return 75, "Valeur estimée (Mode secours)"

pression, vent_vitesse, vent_dir, delta_p = fetch_weather_data(coords["lat"], coords["lon"])
coef_maree, status_maree = fetch_tide_data(coords["port_id"], MAREE_API_KEY)

st.header("2. Conditions Météo & Marée (Temps Réel)")

col_d1, col_d2, col_d3, col_d4 = st.columns(4)
col_d1.metric("Pression", f"{pression:.1f} hPa", delta=f"{delta_p:.1f} hPa/3h")
col_d2.metric("Vent", f"{vent_vitesse:.1f} km/h")
col_d3.metric("Orientation Vent", f"{vent_dir}°")
col_d4.metric("Coef. Marée", f"{coef_maree}", help=status_maree)

# Saisie manuelle restreinte aux paramètres non couverts par l'API
st.subheader("Paramètres de la session")
col_m1, col_m2 = st.columns(2)
with col_m1:
    fenetre_maree = st.selectbox("Fenêtre de marée", ["PM-2h à PM+1h (Optimal)", "Pleine Mer", "Basse Mer", "Autre"])
    houle_hauteur = st.number_input("Hauteur de houle (m)", min_value=0.0, max_value=4.0, value=1.0, step=0.1)
with col_m2:
    carnet_historique = st.slider("Historique de succès (Score Carnet)", 0, 100, 70)

# 4. Calcul du Score V3+
c_maree = 90 if (65 <= coef_maree <= 85 and "PM-2h" in fenetre_maree) else 60
h_carnet = carnet_historique
p_pression = 95 if (-3.0 <= delta_p <= -1.0) else 50

mapping_moment = {
    "Aube (Coup du matin)": 95,
    "Crépuscule (Coup du soir)": 90,
    "Nuit": 78,
    "Matin (Lumière douce)": 65,
    "Après-Midi (Plein soleil)": 48
}
m_moment = mapping_moment[moment]

is_vent_mer = 200 <= vent_dir <= 290
v_vent = 90 if (15 <= vent_vitesse <= 25 and is_vent_mer) else 55
e_eau = 85 if (0.8 <= houle_hauteur <= 1.5) else 50

# Score Global Algorithme V3+
score_global = (0.25 * c_maree) + (0.20 * h_carnet) + (0.15 * p_pression) + (0.15 * m_moment) + (0.15 * v_vent) + (0.10 * e_eau)

# 5. Restitution
st.divider()
st.header("3. Indice d'Activité & Stratégie")

st.metric(label=f"Score d'activité — {spot_nom}", value=f"{round(score_global, 1)} / 100")

if "Aube" in moment or "Crépuscule" in moment:
    technique = "Surface & Sub-surface (Chasses de bordure)"
elif "Nuit" in moment:
    technique = "Pêche lente au leurre dur / leurre souple près des berges"
elif "Après-Midi" in moment:
    technique = "Pêche creuse (cassants, sous-bois d'algues) ou leurre souple/jig"
else:
    technique = "Leurre souple à gratter ou jig léger"

st.success(f"💡 **Technique recommandée** : {technique}")
st.info("📌 **Pêche raisonnée** : Respectez la maille légale (42 cm) et préservez le milieu marin.")