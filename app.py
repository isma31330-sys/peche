import streamlit as st
import requests
import pandas as pd

st.set_page_config(page_title="Aide à la Décision - Pêche au Bar V3+", layout="wide")

st.title("🎣 Aide à la Décision V3+ — Pêche au Bar")
st.caption("Zone 50km Le Croisic & Côte Sauvage | Analyse Météo & Marée Réelle")

API_KEY_MAREE = "9452804b6f6e7a5204505c36d252ea48"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

SPOTS = {
    "Côte Sauvage (Le Croisic)": {"lat": 47.2931, "lon": -2.5204},
    "Pointe du Castelli (Piriac)": {"lat": 47.3781, "lon": -2.5512},
    "Baie de Mesquer": {"lat": 47.3986, "lon": -2.4635},
    "Estuaire de la Loire": {"lat": 47.2300, "lon": -2.1800},
    "Île de Dumet": {"lat": 47.4111, "lon": -2.6208}
}

MOMENTS_MAP = {
    "Aube (Coup du matin)": {"hours": range(5, 8), "weight": 95},
    "Matin (Lumière douce)": {"hours": range(8, 13), "weight": 65},
    "Après-Midi (Plein soleil)": {"hours": range(13, 18), "weight": 48},
    "Crépuscule (Coup du soir)": {"hours": range(18, 22), "weight": 90},
    "Nuit": {"hours": [22, 23, 0, 1, 2, 3, 4], "weight": 78}
}

spot_nom = st.sidebar.selectbox("📍 Secteur de pêche", list(SPOTS.keys()))
coords = SPOTS[spot_nom]

# 1. Météo Open-Meteo
def fetch_weather(lat, lon):
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m,surface_pressure,wind_speed_10m,wind_direction_10m&forecast_days=7&timezone=auto"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            st.error(f"❌ Échec API Météo (Code {res.status_code}) : {res.text}")
            return pd.DataFrame()
        df = pd.DataFrame(res.json()["hourly"])
        df["time"] = pd.to_datetime(df["time"])
        return df
    except Exception as e:
        st.error(f"❌ Erreur réseau Météo : {e}")
        return pd.DataFrame()

# 2. Interrogation stricte d'api-maree.fr
def fetch_api_maree(lat, lon, date_str):
    # Endpoint officiel d'api-maree.fr pour interroger les données par coordonnées/date
    url = f"https://api-maree.fr/ep?key={API_KEY_MAREE}&lat={lat}&lng={lon}&date={date_str}"
    
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        
        if res.status_code != 200:
            st.error(f"❌ Échec API Marée (Code {res.status_code}) : {res.text}")
            return None
            
        data = res.json()
        return data

    except requests.exceptions.RequestException as e:
        st.error(f"❌ Erreur de connexion vers api-maree.fr : {e}")
        return None
    except Exception as e:
        st.error(f"❌ Erreur lors du traitement des données de marée : {e}")
        return None

df_weather = fetch_weather(coords["lat"], coords["lon"])

if not df_weather.empty:
    df_weather["date"] = df_weather["time"].dt.strftime("%Y-%m-%d")
    df_weather["hour"] = df_weather["time"].dt.hour

    def assign_moment(hour):
        for name, cfg in MOMENTS_MAP.items():
            if hour in cfg["hours"]:
                return name
        return "Nuit"

    df_weather["moment"] = df_weather["hour"].apply(assign_moment)

    records = []
    for (date, moment), group in df_weather.groupby(["date", "moment"]):
        wind_speed = group["wind_speed_10m"].mean()
        wind_dir = group["wind_direction_10m"].mean()
        pressure = group["surface_pressure"].mean()

        sub_moment = MOMENTS_MAP[moment]["weight"]
        is_vent_mer = 200 <= wind_dir <= 290
        sub_vent = 90 if (12 <= wind_speed <= 25 and is_vent_mer) else 55
        sub_pression = 85 if pressure < 1015 else 60

        score_total = round((0.40 * sub_moment) + (0.35 * sub_vent) + (0.25 * sub_pression), 1)

        records.append({
            "date": date,
            "moment": moment,
            "score_total": score_total,
            "wind_speed": wind_speed,
            "wind_dir": wind_dir,
            "pressure": pressure
        })

    df_grouped = pd.DataFrame(records)

    st.header("1. Grille des Prévisions Météo (7 Jours)")
    moments_order = ["Aube (Coup du matin)", "Matin (Lumière douce)", "Après-Midi (Plein soleil)", "Crépuscule (Coup du soir)", "Nuit"]
    matrix_df = df_grouped.pivot(index="date", columns="moment", values="score_total")
    matrix_df = matrix_df.reindex(columns=[m for m in moments_order if m in matrix_df.columns])

    st.dataframe(matrix_df.style.background_gradient(cmap="RdYlGn", vmin=40, vmax=90).format("{:.1f}"), use_container_width=True)

    st.divider()
    st.header("2. Analyse Détaillée du Créneau & Marée")

    col_sel1, col_sel2 = st.columns(2)
    with col_sel1:
        selected_date = st.selectbox("Sélectionner la date", df_grouped["date"].unique())
    with col_sel2:
        selected_moment = st.selectbox("Sélectionner le créneau", moments_order)

    row_detail = df_grouped[(df_grouped["date"] == selected_date) & (df_grouped["moment"] == selected_moment)]

    if not row_detail.empty:
        r = row_detail.iloc[0]
        col_m1, col_m2 = st.columns(2)

        with col_m1:
            st.metric(label="Score Conditions Météo", value=f"{r['score_total']} / 100")
            st.write(f"**Vent** : {round(r['wind_speed'], 1)} km/h ({round(r['wind_dir'])}°)")
            st.write(f"**Pression** : {round(r['pressure'], 1)} hPa")

        with col_m2:
            st.subheader("🌊 Informations Marée du Jour (api-maree.fr)")
            
            # Appel à api-maree.fr pour la date sélectionnée
            tide_data = fetch_api_maree(coords["lat"], coords["lon"], selected_date)

            if tide_data:
                # Affichage des champs réels retournés par l'API
                coef = tide_data.get("coefficient", tide_data.get("coef", "N/C"))
                st.write(f"**Coefficient du jour** : **{coef}**")

                if "tides" in tide_data:
                    st.write("**Étales réelles :**")
                    for t in tide_data["tides"]:
                        st.write(f"- **{t.get('type', '')}** : {t.get('time', '')} (Hauteur : {t.get('height', '')}m)")
                elif "etales" in tide_data:
                    st.write(f"**Étales** : {tide_data['etales']}")
                else:
                    st.json(tide_data)

# 3. Widget SHOM
st.divider()
st.header("3. Graphique SHOM Officiel")
shom_url = f"https://services.data.shom.fr/oceano/render/html/widget?duration=4&delta-date=0&lon={coords['lon']}&lat={coords['lat']}&utc=1&lang=fr"
st.components.v1.iframe(shom_url, height=500, scrolling=True)