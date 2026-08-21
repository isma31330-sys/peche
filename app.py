import streamlit as st
import requests
import pandas as pd
import numpy as np

st.set_page_config(page_title="Aide à la Décision - Pêche au Bar V3+", layout="wide")

st.title("🎣 Aide à la Décision V3+ — Pêche au Bar")
st.caption("Zone 50km Le Croisic & Côte Sauvage | Analyse Météo & Conditions")

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

def fetch_weather_and_waves(lat, lon):
    # API Open-Meteo Météo + Vagues (Variables 100% valides)
    url_w = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m,surface_pressure,wind_speed_10m,wind_direction_10m&forecast_days=7&timezone=auto"
    url_m = f"https://marine-api.open-meteo.com/v1/marine?latitude={lat}&longitude={lon}&hourly=wave_height,wave_period&forecast_days=7&timezone=auto"
    
    try:
        res_w = requests.get(url_w, headers=HEADERS, timeout=10)
        res_m = requests.get(url_m, headers=HEADERS, timeout=10)

        if res_w.status_code != 200:
            st.error(f"❌ Échec de l'API Météo (Code {res_w.status_code}) : {res_w.text}")
            return pd.DataFrame()
        if res_m.status_code != 200:
            st.error(f"❌ Échec de l'API Vagues (Code {res_m.status_code}) : {res_m.text}")
            return pd.DataFrame()

        df_w = pd.DataFrame(res_w.json()["hourly"])
        df_m = pd.DataFrame(res_m.json()["hourly"])

        df_w["time"] = pd.to_datetime(df_w["time"])
        df_m["time"] = pd.to_datetime(df_m["time"])

        return pd.merge(df_w, df_m, on="time", how="inner")

    except Exception as e:
        st.error(f"❌ Erreur lors de la récupération météo : {e}")
        return pd.DataFrame()

df = fetch_weather_and_waves(coords["lat"], coords["lon"])

if not df.empty:
    df["date"] = df["time"].dt.strftime("%Y-%m-%d")
    df["hour"] = df["time"].dt.hour

    def assign_moment(hour):
        for name, cfg in MOMENTS_MAP.items():
            if hour in cfg["hours"]:
                return name
        return "Nuit"

    df["moment"] = df["hour"].apply(assign_moment)

    records = []
    for (date, moment), group in df.groupby(["date", "moment"]):
        wind_speed = group["wind_speed_10m"].mean()
        wind_dir = group["wind_direction_10m"].mean()
        pressure = group["surface_pressure"].mean()
        wave_height = group["wave_height"].mean()

        sub_moment = MOMENTS_MAP[moment]["weight"]
        is_vent_mer = 200 <= wind_dir <= 290
        sub_vent = 90 if (12 <= wind_speed <= 25 and is_vent_mer) else 55
        sub_pression = 85 if pressure < 1015 else 60
        sub_houle = 85 if 0.4 <= wave_height <= 1.2 else 50
        sub_carnet = 70

        # Score météo/mer basé sur données réelles API
        score_total = round(
            (0.35 * sub_moment) + 
            (0.25 * sub_vent) + 
            (0.20 * sub_pression) + 
            (0.10 * sub_houle) + 
            (0.10 * sub_carnet), 1
        )

        records.append({
            "date": date,
            "moment": moment,
            "score_total": score_total,
            "wind_speed": wind_speed,
            "wind_dir": wind_dir,
            "pressure": pressure,
            "wave_height": wave_height
        })

    df_grouped = pd.DataFrame(records)

    # 1. Grille Météo
    st.header("1. Grille des Prévisions Météo & Mer (7 Jours)")
    moments_order = ["Aube (Coup du matin)", "Matin (Lumière douce)", "Après-Midi (Plein soleil)", "Crépuscule (Coup du soir)", "Nuit"]
    matrix_df = df_grouped.pivot(index="date", columns="moment", values="score_total")
    matrix_df = matrix_df.reindex(columns=[m for m in moments_order if m in matrix_df.columns])

    st.dataframe(
        matrix_df.style.background_gradient(cmap="RdYlGn", vmin=40, vmax=90).format("{:.1f}"),
        use_container_width=True
    )

    # 2. Vue Détaillée
    st.divider()
    st.header("2. Analyse Détaillée du Créneau")

    col_sel1, col_sel2 = st.columns(2)
    with col_sel1:
        selected_date = st.selectbox("Sélectionner la date", df_grouped["date"].unique())
    with col_sel2:
        selected_moment = st.selectbox("Sélectionner le créneau", moments_order)

    row_detail = df_grouped[(df_grouped["date"] == selected_date) & (df_grouped["moment"] == selected_moment)]

    if not row_detail.empty:
        r = row_detail.iloc[0]
        st.metric(label=f"Score Météo / Vent / Pression", value=f"{r['score_total']} / 100")
        st.write(f"**Vent moyen** : {round(r['wind_speed'], 1)} km/h ({round(r['wind_dir'])}°)")
        st.write(f"**Pression** : {round(r['pressure'], 1)} hPa")
        st.write(f"**Hauteur de houle** : {round(r['wave_height'], 2)} m")

# 3. Widget SHOM Officiel (Seule source 100% exacte pour les marées FR)
st.divider()
st.header("3. Marée Exacte & Océanogramme SHOM")
st.info("Pour éviter toute approximation sur le calcul des coefficients et des hauteurs d'eau, le graphique officiel du SHOM est intégré directement ci-dessous.")
shom_url = f"https://services.data.shom.fr/oceano/render/html/widget?duration=4&delta-date=0&lon={coords['lon']}&lat={coords['lat']}&utc=1&lang=fr"
st.components.v1.iframe(shom_url, height=550, scrolling=True)