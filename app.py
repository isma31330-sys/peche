import streamlit as st
import requests
import pandas as pd

st.set_page_config(page_title="Aide à la Décision - Pêche au Bar V3+", layout="wide")

st.title("🎣 Aide à la Décision V3+ — Pêche au Bar")
st.caption("Zone 50km Le Croisic & Côte Sauvage | Prévisions 15J & Décomposition")

# 1. Configuration des Spots GPS
SPOTS = {
    "Côte Sauvage (Le Croisic)": {"lat": 47.2931, "lon": -2.5204},
    "Pointe du Castelli (Piriac)": {"lat": 47.3781, "lon": -2.5512},
    "Baie de Mesquer": {"lat": 47.3986, "lon": -2.4635},
    "Estuaire de la Loire": {"lat": 47.2300, "lon": -2.1800},
    "Île de Dumet": {"lat": 47.4111, "lon": -2.6208}
}

MOMENTS_MAP = {
    "Aube (Coup du matin)": 95,
    "Matin (Lumière douce)": 65,
    "Après-Midi (Plein soleil)": 48,
    "Crépuscule (Coup du soir)": 90,
    "Nuit": 78
}

spot_nom = st.sidebar.selectbox("📍 Secteur de pêche", list(SPOTS.keys()))
coords = SPOTS[spot_nom]

# 2. Récupération Marée Gratuite (Open-Meteo Marine)
@st.cache_data(ttl=3600)
def fetch_tide_data(lat, lon, target_date):
    url = f"https://marine-api.open-meteo.com/v1/marine?latitude={lat}&longitude={lon}&hourly=sea_level_height_above_mean_sea_level&forecast_days=16&timezone=auto"
    try:
        res = requests.get(url, timeout=5).json()
        hourly = res.get("hourly", {})
        if hourly:
            df_tide = pd.DataFrame(hourly)
            df_tide["time"] = pd.to_datetime(df_tide["time"])
            df_day = df_tide[df_tide["time"].dt.strftime("%Y-%m-%d") == target_date].copy()
            
            if not df_day.empty:
                heights = df_day["sea_level_height_above_mean_sea_level"].tolist()
                
                # Calcul de l'mplitude pour estimer le coefficient
                amp = max(heights) - min(heights)
                estimated_coef = min(120, max(20, int(amp * 22 + 20)))
                
                # Détection des pics (PM) et creux (BM)
                extrema = []
                for i in range(1, len(df_day) - 1):
                    prev_h = heights[i-1]
                    curr_h = heights[i]
                    next_h = heights[i+1]
                    t_str = df_day.iloc[i]["time"].strftime("%H:%M")
                    
                    if curr_h > prev_h and curr_h > next_h:
                        extrema.append(f"{t_str} (PM)")
                    elif curr_h < prev_h and curr_h < next_h:
                        extrema.append(f"{t_str} (BM)")
                
                str_horaires = " | ".join(extrema) if extrema else "Données de marée lissées"
                return estimated_coef, str_horaires
    except Exception:
        pass
    return "N/A", "Indisponible"

# 3. Récupération Météo 16J (Open-Meteo)
@st.cache_data(ttl=3600)
def fetch_15day_hourly(lat, lon):
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m,surface_pressure,wind_speed_10m,wind_direction_10m&forecast_days=16&timezone=auto"
    try:
        res = requests.get(url, timeout=10).json()
        return res.get("hourly", {})
    except Exception:
        return {}

hourly_raw = fetch_15day_hourly(coords["lat"], coords["lon"])

if hourly_raw:
    df_raw = pd.DataFrame(hourly_raw)
    df_raw["time"] = pd.to_datetime(df_raw["time"])
    df_raw["date"] = df_raw["time"].dt.strftime("%Y-%m-%d")
    df_raw["hour"] = df_raw["time"].dt.hour

    def get_moment_category(hour):
        if 5 <= hour < 8:
            return "Aube (Coup du matin)"
        elif 8 <= hour < 13:
            return "Matin (Lumière douce)"
        elif 13 <= hour < 18:
            return "Après-Midi (Plein soleil)"
        elif 18 <= hour < 22:
            return "Crépuscule (Coup du soir)"
        else:
            return "Nuit"

    df_raw["moment"] = df_raw["hour"].apply(get_moment_category)

    df_grouped = df_raw.groupby(["date", "moment"]).agg({
        "wind_speed_10m": "mean",
        "wind_direction_10m": "mean",
        "surface_pressure": "mean"
    }).reset_index()

    # Calcul des scores V3+
    def calculate_score(row):
        sub_moment = MOMENTS_MAP.get(row["moment"], 60)
        sub_maree = 85 if row["moment"] in ["Aube (Coup du matin)", "Crépuscule (Coup du soir)"] else 65
        
        is_vent_mer = 200 <= row["wind_direction_10m"] <= 290
        sub_vent = 90 if (12 <= row["wind_speed_10m"] <= 25 and is_vent_mer) else 55
        sub_pression = 85 if row["surface_pressure"] < 1015 else 60
        
        sub_houle = 75
        sub_carnet = 70

        c_maree = 0.25 * sub_maree
        c_carnet = 0.20 * sub_carnet
        c_pression = 0.15 * sub_pression
        c_moment = 0.15 * sub_moment
        c_vent = 0.15 * sub_vent
        c_houle = 0.10 * sub_houle

        total = c_maree + c_carnet + c_pression + c_moment + c_vent + c_houle
        
        return pd.Series([
            round(total, 1), sub_maree, sub_carnet, sub_pression, 
            sub_moment, sub_vent, sub_houle,
            c_maree, c_carnet, c_pression, c_moment, c_vent, c_houle
        ])

    score_cols = [
        "score_total", "sub_maree", "sub_carnet", "sub_pression", 
        "sub_moment", "sub_vent", "sub_houle",
        "c_maree", "c_carnet", "c_pression", "c_moment", "c_vent", "c_houle"
    ]
    df_grouped[score_cols] = df_grouped.apply(calculate_score, axis=1)

    # 4. Grille des Prévisions (Matrice)
    st.header("1. Grille des Prévisions sur 15 Jours (Par Créneau)")
    moments_order = ["Aube (Coup du matin)", "Matin (Lumière douce)", "Après-Midi (Plein soleil)", "Crépuscule (Coup du soir)", "Nuit"]
    matrix_df = df_grouped.pivot(index="date", columns="moment", values="score_total")
    matrix_df = matrix_df.reindex(columns=[m for m in moments_order if m in matrix_df.columns])

    try:
        st.dataframe(
            matrix_df.style.background_gradient(cmap="RdYlGn", vmin=40, vmax=90).format("{:.1f}"),
            use_container_width=True,
            height=400
        )
    except Exception:
        st.dataframe(matrix_df, use_container_width=True, height=400)

    # 5. Inspection Détaillée + Marée
    st.divider()
    st.header("2. Analyse Détaillée du Créneau & Marée")
    
    col_sel1, col_sel2 = st.columns(2)
    with col_sel1:
        selected_date = st.selectbox("Sélectionner la date", df_grouped["date"].unique())
    with col_sel2:
        selected_moment = st.selectbox("Sélectionner le créneau", moments_order)

    # Récupération dynamique de la marée pour la date SÉLECTIONNÉE
    coef_maree, horaires_maree = fetch_tide_data(coords["lat"], coords["lon"], selected_date)

    row_detail = df_grouped[(df_grouped["date"] == selected_date) & (df_grouped["moment"] == selected_moment)]

    if not row_detail.empty:
        r = row_detail.iloc[0]
        
        col_res1, col_res2 = st.columns([1, 2])
        
        with col_res1:
            st.metric(
                label=f"Score Global ({selected_date} — {selected_moment[:4]})", 
                value=f"{r['score_total']} / 100"
            )

            st.markdown("### 🌊 Informations Marée")
            st.info(f"**Coeff. estimé** : {coef_maree}\n\n**Étales (BM/PM)** : {horaires_maree}")

            st.markdown("### 🍃 Conditions Météo")
            st.write(f"**Vent moyen** : {round(r['wind_speed_10m'], 1)} km/h ({round(r['wind_direction_10m'])}°)")
            st.write(f"**Pression** : {round(r['surface_pressure'], 1)} hPa")

            if "Aube" in selected_moment or "Crépuscule" in selected_moment:
                st.success("💡 **Stratégie** : Leurres de surface & sub-surface (chasses de bordure).")
            elif "Nuit" in selected_moment:
                st.info("💡 **Stratégie** : Pêche lente au leurre dur / souple près des berges.")
            else:
                st.warning("💡 **Stratégie** : Pêche creuse (cassants, sous-bois d'algues) au leurre souple.")

        with col_res2:
            st.subheader("📊 Décomposition des points apportés au score")
            
            df_decomp = pd.DataFrame({
                "Critère": [
                    "Marée & Courant (25%)", 
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

# 6. Océanogramme SHOM
st.divider()
st.header("3. Océanogramme SHOM (Marée & Hauteur d'eau exactes)")
shom_url = f"https://services.data.shom.fr/oceano/render/html/widget?duration=4&delta-date=0&lon={coords['lon']}&lat={coords['lat']}&utc=1&lang=fr"
st.components.v1.iframe(shom_url, height=550, scrolling=True)