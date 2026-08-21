import streamlit as st
import requests
import pandas as pd
import numpy as np

st.set_page_config(page_title="Aide à la Décision - Pêche au Bar V3+", layout="wide")

st.title("🎣 Aide à la Décision V3+ — Pêche au Bar")
st.caption("Zone 50km Le Croisic & Côte Sauvage | Calcul Marée Horaire Exacte & Météo")

# 1. Configuration des Spots GPS
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

# 2. Récupération Météo & Hauteurs d'eau (Open-Meteo)
@st.cache_data(ttl=3600)
def fetch_marine_data(lat, lon):
    url = f"https://marine-api.open-meteo.com/v1/marine?latitude={lat}&longitude={lon}&hourly=sea_level_height_above_mean_sea_level&forecast_days=16&timezone=auto"
    try:
        res = requests.get(url, timeout=10).json()
        return pd.DataFrame(res.get("hourly", {}))
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def fetch_weather_data(lat, lon):
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m,surface_pressure,wind_speed_10m,wind_direction_10m&forecast_days=16&timezone=auto"
    try:
        res = requests.get(url, timeout=10).json()
        return pd.DataFrame(res.get("hourly", {}))
    except Exception:
        return pd.DataFrame()

df_tide = fetch_marine_data(coords["lat"], coords["lon"])
df_weather = fetch_weather_data(coords["lat"], coords["lon"])

if not df_tide.empty and not df_weather.empty:
    df_tide["time"] = pd.to_datetime(df_tide["time"])
    df_weather["time"] = pd.to_datetime(df_weather["time"])

    # Détection horaire des étales PM / BM
    heights = df_tide["sea_level_height_above_mean_sea_level"].values
    tide_type = ["--"] * len(heights)
    
    for i in range(1, len(heights) - 1):
        if heights[i] > heights[i-1] and heights[i] > heights[i+1]:
            tide_type[i] = "PM"
        elif heights[i] < heights[i-1] and heights[i] < heights[i+1]:
            tide_type[i] = "BM"
            
    df_tide["tide_event"] = tide_type

    # Fusion Météo + Marée heure par heure
    df = pd.merge(df_weather, df_tide[["time", "sea_level_height_above_mean_sea_level", "tide_event"]], on="time")
    df["date"] = df["time"].dt.strftime("%Y-%m-%d")
    df["hour"] = df["time"].dt.hour

    # Calcul quotidien du marnage et du coefficient du jour
    daily_stats = df.groupby("date")["sea_level_height_above_mean_sea_level"].agg(["min", "max"]).reset_index()
    daily_stats["marnage"] = daily_stats["max"] - daily_stats["min"]
    daily_stats["coef"] = (daily_stats["marnage"] * 18.5 + 20).clip(30, 115).astype(int)

    df = pd.merge(df, daily_stats[["date", "coef"]], on="date")

    # Attribution du moment de la journée
    def assign_moment(hour):
        for name, cfg in MOMENTS_MAP.items():
            if hour in cfg["hours"]:
                return name
        return "Nuit"

    df["moment"] = df["hour"].apply(assign_moment)

    # 3. Aggrégation et calcul des scores croisés par créneau
    def process_slot_score(group):
        date = group["date"].iloc[0]
        moment = group["moment"].iloc[0]
        coef = group["coef"].iloc[0]
        
        wind_speed = group["wind_speed_10m"].mean()
        wind_dir = group["wind_direction_10m"].mean()
        pressure = group["surface_pressure"].mean()

        # ÉVALUATION DE LA MARÉE DANS CE CRÉNEAU
        has_pm = "PM" in group["tide_event"].values
        has_bm = "BM" in group["tide_event"].values

        # Calcul sous-score Marée
        if coef >= 80:
            base_coef_score = 90
        elif coef >= 55:
            base_coef_score = 75
        else:
            base_coef_score = 55

        # La présence de la pleine mer (PM) sur le créneau booste la note
        if has_pm:
            sub_maree = min(100, base_coef_score + 15)
        elif has_bm:
            sub_maree = base_coef_score - 5
        else:
            sub_maree = base_coef_score

        # Sous-score Moment
        sub_moment = MOMENTS_MAP[moment]["weight"]

        # Sous-score Vent (Onshore = 200° à 290°)
        is_vent_mer = 200 <= wind_dir <= 290
        sub_vent = 90 if (12 <= wind_speed <= 25 and is_vent_mer) else 55

        # Autres sous-scores
        sub_pression = 85 if pressure < 1015 else 60
        sub_houle = 75
        sub_carnet = 70

        # PONDÉRATION (100%)
        c_maree = 0.25 * sub_maree
        c_carnet = 0.20 * sub_carnet
        c_pression = 0.15 * sub_pression
        c_moment = 0.15 * sub_moment
        c_vent = 0.15 * sub_vent
        c_houle = 0.10 * sub_houle

        score_total = round(c_maree + c_carnet + c_pression + c_moment + c_vent + c_houle, 1)

        # Extraction des heures exactes de PM/BM du créneau/jour
        events = group[group["tide_event"] != "--"]
        etales_str = " | ".join([f"{r['tide_event']}: {r['time'].strftime('%H:%M')}" for _, r in events.iterrows()]) if not events.empty else "Pas d'étale dans ce créneau"

        return pd.Series({
            "score_total": score_total,
            "coef": coef,
            "sub_maree": sub_maree,
            "sub_carnet": sub_carnet,
            "sub_pression": sub_pression,
            "sub_moment": sub_moment,
            "sub_vent": sub_vent,
            "sub_houle": sub_houle,
            "c_maree": c_maree,
            "c_carnet": c_carnet,
            "c_pression": c_pression,
            "c_moment": c_moment,
            "c_vent": c_vent,
            "c_houle": c_houle,
            "wind_speed": wind_speed,
            "wind_dir": wind_dir,
            "pressure": pressure,
            "etales_slot": etales_str
        })

    df_grouped = df.groupby(["date", "moment"]).apply(process_slot_score, include_groups=False).reset_index()

    # 4. Grille des Prévisions (Matrice)
    st.header("1. Grille des Prévisions sur 15 Jours")
    moments_order = ["Aube (Coup du matin)", "Matin (Lumière douce)", "Après-Midi (Plein soleil)", "Crépuscule (Coup du soir)", "Nuit"]
    matrix_df = df_grouped.pivot(index="date", columns="moment", values="score_total")
    matrix_df = matrix_df.reindex(columns=[m for m in moments_order if m in matrix_df.columns])

    st.dataframe(
        matrix_df.style.background_gradient(cmap="RdYlGn", vmin=40, vmax=90).format("{:.1f}"),
        use_container_width=True,
        height=400
    )

    # 5. Vue Détaillée
    st.divider()
    st.header("2. Analyse Détaillée du Créneau & Marée")

    col_sel1, col_sel2 = st.columns(2)
    with col_sel1:
        selected_date = st.selectbox("Sélectionner la date", df_grouped["date"].unique())
    with col_sel2:
        selected_moment = st.selectbox("Sélectionner le créneau", moments_order)

    # Horaires PM/BM sur toute la journée sélectionnée
    df_day = df[df["date"] == selected_date]
    day_events = df_day[df_day["tide_event"] != "--"]
    all_day_etales = " | ".join([f"{r['tide_event']}: {r['time'].strftime('%H:%M')}" for _, r in day_events.iterrows()])

    row_detail = df_grouped[(df_grouped["date"] == selected_date) & (df_grouped["moment"] == selected_moment)]

    if not row_detail.empty:
        r = row_detail.iloc[0]
        col_res1, col_res2 = st.columns([1, 2])

        with col_res1:
            st.metric(
                label=f"Score Global ({selected_date} — {selected_moment[:4]})", 
                value=f"{r['score_total']} / 100"
            )

            st.markdown("### 🌊 Marée Exacte du Jour")
            st.info(f"**Coefficient du jour** : {r['coef']}\n\n**Étales du jour** : {all_day_etales}\n\n**Événement sur ce créneau** : {r['etales_slot']}")

            st.markdown("### 🍃 Conditions Météo")
            st.write(f"**Vent moyen** : {round(r['wind_speed'], 1)} km/h ({round(r['wind_dir'])}°)")
            st.write(f"**Pression** : {round(r['pressure'], 1)} hPa")

        with col_res2:
            st.subheader("📊 Décomposition des points apportés au score")
            df_decomp = pd.DataFrame({
                "Critère": [
                    "Marée & Coeff (25%)", 
                    "Carnet & Historique (20%)", 
                    "Pression Atm. (15%)", 
                    "Moment du Jour (15%)", 
                    "Vent & Orientation (15%)", 
                    "Houle & Eau (10%)"
                ],
                "Score Brut (/100)": [
                    r["sub_maree"], r["sub_carnet"], r["sub_pression"], 
                    r["sub_moment"], r["sub_vent"], r["sub_houle"]
                ],
                "Points apportés": [
                    r["c_maree"], r["c_carnet"], r["c_pression"], 
                    r["c_moment"], r["c_vent"], r["c_houle"]
                ]
            }).set_index("Critère")

            st.bar_chart(df_decomp["Points apportés"])
            st.table(df_decomp)

# 6. Widget SHOM
st.divider()
st.header("3. Océanogramme SHOM (Graphique en Direct)")
shom_url = f"https://services.data.shom.fr/oceano/render/html/widget?duration=4&delta-date=0&lon={coords['lon']}&lat={coords['lat']}&utc=1&lang=fr"
st.components.v1.iframe(shom_url, height=550, scrolling=True)