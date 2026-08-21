import streamlit as st
import requests
import pandas as pd

st.set_page_config(page_title="Aide à la Décision - Pêche au Bar V3+", layout="wide")

st.title("🎣 Aide à la Décision V3+ — Pêche au Bar")
st.caption("Zone 50km Le Croisic & Côte Sauvage | Décomposition du Score & Variables Temporelles")

# Spots GPS & ID Ports
SPOTS = {
    "Côte Sauvage (Le Croisic)": {"lat": 47.2931, "lon": -2.5204, "port_id": "80"},
    "Pointe du Castelli (Piriac)": {"lat": 47.3781, "lon": -2.5512, "port_id": "80"},
    "Baie de Mesquer": {"lat": 47.3986, "lon": -2.4635, "port_id": "80"},
    "Estuaire de la Loire": {"lat": 47.2300, "lon": -2.1800, "port_id": "82"},
    "Île de Dumet": {"lat": 47.4111, "lon": -2.6208, "port_id": "80"}
}

MAREE_API_KEY = st.secrets.get("MAREE_API_KEY", "VOTRE_CLE_API_MAREE")

# 1. Sélection de la zone et de l'heure/marée
st.header("1. Paramètres de la Session")
col_s1, col_s2, col_s3 = st.columns(3)

with col_s1:
    spot_nom = st.selectbox("Secteur de pêche", list(SPOTS.keys()))
    coords = SPOTS[spot_nom]

with col_s2:
    moment = st.selectbox(
        "Moment du jour",
        ["Aube (Coup du matin)", "Matin (Lumière douce)", "Après-Midi (Plein soleil)", "Crépuscule (Coup du soir)", "Nuit"]
    )

with col_s3:
    etat_maree = st.selectbox(
        "Phase de marée",
        ["PM-2h à PM+1h (Plein courant / Optimal)", "Montante (Etale BM à PM)", "Descendante (Jusant)", "Basse Mer (Etale)"]
    )

# 2. Récupération Météo (Open-Meteo)
@st.cache_data(ttl=1800)
def fetch_current_weather(lat, lon):
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=surface_pressure,wind_speed_10m,wind_direction_10m&hourly=surface_pressure&forecast_days=1"
    try:
        res = requests.get(url).json()
        current = res.get("current", {})
        hourly = res.get("hourly", {})
        pression = current.get("surface_pressure", 1013.25)
        vent_vitesse = current.get("wind_speed_10m", 15.0)
        vent_dir = current.get("wind_direction_10m", 270)
        pressions_hourly = hourly.get("surface_pressure", [])
        delta_p = (pressions_hourly[3] - pressions_hourly[0]) if len(pressions_hourly) >= 4 else -1.5
        return pression, vent_vitesse, vent_dir, delta_p
    except Exception:
        return 1013.25, 20.0, 240, -1.5

pression, vent_vitesse, vent_dir, delta_p = fetch_current_weather(coords["lat"], coords["lon"])

# 3. Calcul des sous-scores pondérés (V3+)
score_moment_map = {
    "Aube (Coup du matin)": 95,
    "Crépuscule (Coup du soir)": 90,
    "Nuit": 78,
    "Matin (Lumière douce)": 65,
    "Après-Midi (Plein soleil)": 48
}
sub_moment = score_moment_map[moment]

score_maree_map = {
    "PM-2h à PM+1h (Plein courant / Optimal)": 95,
    "Montante (Etale BM à PM)": 75,
    "Descendante (Jusant)": 65,
    "Basse Mer (Etale)": 40
}
sub_maree = score_maree_map[etat_maree]

sub_pression = 95 if (-3.0 <= delta_p <= -1.0) else (70 if delta_p < 0 else 45)

is_vent_mer = 200 <= vent_dir <= 290
sub_vent = 90 if (12 <= vent_vitesse <= 25 and is_vent_mer) else 55

sub_houle = 80
sub_carnet = 75

# Impact pondéré sur le score final (Base /100)
contrib_maree = 0.25 * sub_maree
contrib_carnet = 0.20 * sub_carnet
contrib_pression = 0.15 * sub_pression
contrib_moment = 0.15 * sub_moment
contrib_vent = 0.15 * sub_vent
contrib_houle = 0.10 * sub_houle

score_global = contrib_maree + contrib_carnet + contrib_pression + contrib_moment + contrib_vent + contrib_houle

# 4. Affichage du Score et Décomposition
st.divider()
st.header("2. Indice d'Activité & Décomposition du Score")

col_res1, col_res2 = st.columns([1, 2])

with col_res1:
    st.metric(label=f"Score d'Activité Global — {spot_nom}", value=f"{round(score_global, 1)} / 100")
    
    if "Aube" in moment or "Crépuscule" in moment:
        st.success("💡 **Stratégie** : Leurres de surface & sub-surface (chasses de bordure).")
    elif "Nuit" in moment:
        st.info("💡 **Stratégie** : Pêche lente au leurre dur / souple près des berges.")
    else:
        st.warning("💡 **Stratégie** : Pêche creuse (cassants, sous-bois d'algues) au leurre souple.")

with col_res2:
    st.subheader("📊 Contribution de chaque critère au score")
    
    df_decomp = pd.DataFrame({
        "Critère": ["Marée & Courant (25%)", "Carnet & Historique (20%)", "Pression Atm. (15%)", "Moment du Jour (15%)", "Vent & Orientation (15%)", "Houle & Eau (10%)"],
        "Score Brut (/100)": [sub_maree, sub_carnet, sub_pression, sub_moment, sub_vent, sub_houle],
        "Points apportés": [contrib_maree, contrib_carnet, contrib_pression, contrib_moment, contrib_vent, contrib_houle]
    }).set_index("Critère")
    
    st.bar_chart(df_decomp["Points apportés"])

st.table(df_decomp)

# 5. Océanogramme SHOM
st.divider()
st.header("3. Océanogramme SHOM")
shom_url = f"https://services.data.shom.fr/oceano/render/html/widget?duration=4&delta-date=0&lon={coords['lon']}&lat={coords['lat']}&utc=1&lang=fr"
st.components.v1.iframe(shom_url, height=550, scrolling=True)