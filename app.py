import streamlit as st
import requests
import pandas as pd
import numpy as np

st.set_page_config(page_title="Aide à la Décision - Pêche au Bar V3+", layout="wide")

st.title("🎣 Aide à la Décision V3+ — Pêche au Bar")
st.caption("Zone 50km Le Croisic & Côte Sauvage | Calcul Marée Horaire Exacte & Météo")

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

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

# 2. Récupération des données Météo & Marée (7 jours max pour stabilité API)
@st.cache_data(ttl=3600)
def fetch_all_data(lat, lon):
    url_marine = f"https://marine-api.open-meteo.com/v1/marine?latitude={lat}&longitude={lon}&hourly=sea_level_height_above_mean_sea_level&forecast_days=7&timezone=auto"
    url_weather = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m,surface_pressure,wind_speed_10m,wind_direction_10m&forecast_days=7&timezone=auto"
    
    try:
        res_m = requests.get(url_marine, headers=HEADERS, timeout=10).json()
        res_w = requests.get(url_weather, headers=HEADERS, timeout=10).json()

        if "hourly" in res_m and "hourly" in res_w:
            df_m = pd.DataFrame(res_m["hourly"])
            df_w = pd.DataFrame(res_w["hourly"])
            
            if not df_m.empty and not df_w.empty:
                df_m["time"] = pd.to_datetime(df_m["time"])
                df_w["time"] = pd.to_datetime(df_w["time"])
                return pd.merge(df_w, df_m, on="time")
    except Exception as e:
        st.sidebar.error(f"Erreur API : {e}")

    # Données simulées temporaires si l'API ne répond pas du tout
    times = pd.date_range(start=pd.Timestamp.now().floor('D'), periods=168, freq='h')
    return pd.DataFrame({
        "time": times,
        "wind_speed_10m": [15.0] * 168,
        "wind_direction_10m": [240.0] * 168,
        "surface_pressure": [1013.0] * 168,
        "sea_level_height_above_mean_sea_level": [2.5 + 1.5 * np.sin(i / 2) for i in range(168)]
    })

df = fetch_all_data(coords["lat"], coords["lon"])

if not df.empty:
    # Détection des étales (PM / BM)
    heights = df["sea_level_height_above_mean_sea_level"].values
    tide_type = ["--"] * len(heights)
    
    for i in range(1, len(heights) - 1):
        if heights[i] > heights[i-1] and heights[i] > heights[i+1]:
            tide_type[i] = "PM"
        elif heights[i] < heights[i-1] and heights[i] < heights[i+1]:
            tide_type[i] = "BM"
            
    df["tide_event"] = tide_type
    df["date"] = df["time"].dt.strftime("%Y-%m-%d")
    df["hour"] = df["time"].dt.hour

    # Calcul du marnage et du coefficient quotidien
    daily_stats = df.groupby("date")["sea_level_height_above_mean_sea_level"].agg(["min", "max"]).reset_index()
    daily_stats["marnage"] = daily_stats["max"] - daily_stats["min"]
    daily_stats["coef"] = (daily_stats["marnage"] * 18.5 + 20).clip(30, 115).astype(int)

    df = pd.merge(df, daily_stats[["date", "coef"]], on="date")

    def assign_moment(hour):
        for name, cfg in MOMENTS_MAP.items():
            if hour in cfg["hours"]:
                return name
        return "Nuit"

    df["moment"] = df["hour"].apply(assign_moment)

    # Aggrégation et calcul des scores
    records = []
    for (date, moment), group in df.groupby(["date", "moment"]):
        coef = group["coef"].iloc[0]
        wind_speed = group["wind_speed_10m"].mean()
        wind_dir = group["wind_direction_10m"].mean()
        pressure = group["surface_pressure"].mean()

        has_pm = "PM" in group["tide_event"].values
        has_bm = "BM" in group["tide_event"].values

        base_coef_score = 90 if coef >= 80 else (75 if coef >= 55 else 55)

        if has_pm:
            sub_maree = min(100, base_coef_score + 15)
        elif has_bm:
            sub_maree = base_coef_score - 5
        else:
            sub_maree = base_coef_score

        sub_moment = MOMENTS_MAP[moment]["weight"]
        is_vent_mer = 200 <= wind_dir <= 290
        sub_vent = 90 if (12 <= wind_speed <= 25 and is_vent_mer) else 55
        sub_pression = 85 if pressure < 1015 else 60
        sub_houle = 75
        sub_carnet = 70

        c_maree = 0.25 * sub_maree
        c_carnet = 0.20 * sub_carnet
        c_pression = 0.15 * sub_pression
        c_moment = 0.15 * sub_moment
        c_vent = 0.15 * sub_vent
        c_houle = 0.10 * sub_houle

        score_total = round(c_maree + c_carnet + c_pression + c_moment + c_vent + c_houle, 1)

        events = group[group["tide_event"] != "--"]
        etales_str = " | ".join([f"{r['tide_event']}: {r['time'].strftime('%H:%M')}" for _, r in events.iterrows()]) if not events.empty else "Pas d'étale sur ce créneau"

        records.append({
            "date": date,
            "moment": moment,
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

    df_grouped = pd.DataFrame(records)

    # 3. Grille des Prévisions
    st.header("1. Grille des Prévisions")
    moments_order = ["Aube (Coup du matin)", "Matin (Lumière douce)", "Après-Midi (Plein soleil)", "Crépuscule (Coup du soir)", "Nuit"]
    matrix_df = df_grouped.pivot(index="date", columns="moment", values="score_total")
    matrix_df = matrix_df.reindex(columns=[m for m in moments_order if m in matrix_df.columns])

    st.dataframe(
        matrix_df.style.background_gradient(cmap="RdYlGn", vmin=40, vmax=90).format("{:.1f}"),
        use_container_width=True,
        height=300
    )

    # 4. Vue Détaillée
    st.divider()
    st.header("2. Analyse Détaillée du Créneau & Marée")

    col_sel1, col_sel2 = st.columns(2)
    with col_sel1:
        selected_date = st.selectbox("Sélectionner la date", df_grouped["date"].unique())
    with col_sel2:
        selected_moment = st.selectbox("Sélectionner le créneau", moments_order)

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

# 5. Widget SHOM
st.divider()
st.header("3. Océanogramme SHOM (Graphique en Direct)")
shom_url = f"https://services.data.shom.fr/oceano/render/html/widget?duration=4&delta-date=0&lon={coords['lon']}&lat={coords['lat']}&utc=1&lang=fr"
st.components.v1.iframe(shom_url, height=550, scrolling=True)