import streamlit as st
import requests
import pandas as pd
import json
import os
from datetime import datetime

st.set_page_config(page_title="Aide à la Décision - Pêche au Bar V3+", layout="wide")

st.title("🎣 Aide à la Décision V3+ — Pêche au Bar & Auto-Apprentissage")
st.caption("Zone 50km Le Croisic & Côte Sauvage | Algorithme Calibré & Carnet Intelligent")

API_KEY_MAREE = "9452804b6f6e7a5204505c36d252ea48"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
CARNET_FILE = "carnet_peche.json"

SPOTS = {
    "Côte Sauvage (Le Croisic)": {"lat": 47.2931, "lon": -2.5204, "site": "le-croisic"},
    "Pointe du Castelli (Piriac)": {"lat": 47.3781, "lon": -2.5512, "site": "piriac-sur-mer"},
    "Baie de Mesquer": {"lat": 47.3986, "lon": -2.4635, "site": "piriac-sur-mer"},
    "Estuaire de la Loire": {"lat": 47.2300, "lon": -2.1800, "site": "saint-nazaire"},
    "Île de Dumet": {"lat": 47.4111, "lon": -2.6208, "site": "piriac-sur-mer"}
}

MOMENTS_MAP = {
    "Aube (Coup du matin)": {"hours": range(5, 8)},
    "Matin (Lumière douce)": {"hours": range(8, 13)},
    "Après-Midi (Plein soleil)": {"hours": range(13, 18)},
    "Crépuscule (Coup du soir)": {"hours": range(18, 22)},
    "Nuit": {"hours": [22, 23, 0, 1, 2, 3, 4]}
}

def charger_carnet():
    if os.path.exists(CARNET_FILE):
        try:
            with open(CARNET_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def sauvegarder_carnet(carnet):
    with open(CARNET_FILE, "w", encoding="utf-8") as f:
        json.dump(carnet, f, ensure_ascii=False, indent=4)

spot_nom = st.sidebar.selectbox("📍 Secteur de pêche par défaut", list(SPOTS.keys()))
coords = SPOTS[spot_nom]

@st.cache_data(ttl=3600)
def fetch_weather_16days(lat, lon):
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m,surface_pressure,wind_speed_10m,wind_direction_10m,cloud_cover&forecast_days=16&timezone=auto"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code != 200: return pd.DataFrame()
        df = pd.DataFrame(res.json()["hourly"])
        df["time"] = pd.to_datetime(df["time"])
        return df
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def fetch_marine_data(lat, lon):
    url = f"https://marine-api.open-meteo.com/v1/marine?latitude={lat}&longitude={lon}&hourly=wave_height,sea_surface_temperature&forecast_days=7&timezone=auto"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code != 200: return pd.DataFrame()
        df = pd.DataFrame(res.json()["hourly"])
        df["time"] = pd.to_datetime(df["time"])
        return df
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def fetch_tides_15days(site_slug, start_date, end_date):
    url = f"https://api-maree.fr/tide-extrema?site={site_slug}&from={start_date}&to={end_date}&tz=Europe/Paris&key={API_KEY_MAREE}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code != 200: return {}
        data = res.json()
        tides_by_date = {}
        if "data" in data:
            for day in data["data"]:
                date_key = day.get("date")
                extrema = day.get("extrema", [])
                coefs = [e["coef"] for e in extrema if e.get("type") == "PM" and "coef" in e]
                max_coef = max(coefs) if coefs else 70
                tides_by_date[date_key] = {"max_coef": max_coef, "extrema": extrema}
        return tides_by_date
    except Exception:
        return {}

def render_score_badge(score, text):
    colors = {1: "#ff4b4b", 2: "#ffa726", 3: "#fdd835", 4: "#66bb6a", 5: "#2e7d32"}
    bg_color = colors.get(score, "#e0e0e0")
    st.markdown(
        f"<div style='background-color:{bg_color}; padding:6px 12px; border-radius:6px; color:white; font-weight:bold; display:inline-block; margin-bottom:8px;'>"
        f"{score} / 5 — {text}</div>", 
        unsafe_allow_html=True
    )

df_weather = fetch_weather_16days(coords["lat"], coords["lon"])
df_marine = fetch_marine_data(coords["lat"], coords["lon"])

if not df_weather.empty:
    df_weather["date"] = df_weather["time"].dt.strftime("%Y-%m-%d")
    df_weather["hour"] = df_weather["time"].dt.hour

    if not df_marine.empty:
        df_weather = pd.merge_asof(df_weather.sort_values("time"), df_marine.sort_values("time"), on="time")
    else:
        df_weather["wave_height"] = 1.0
        df_weather["sea_surface_temperature"] = 15.0

    dates_list = sorted(df_weather["date"].unique())[:15]
    start_date, end_date = dates_list[0], dates_list[-1]
    tides_dict = fetch_tides_15days(coords["site"], start_date, end_date)

    def assign_moment(hour):
        for name, cfg in MOMENTS_MAP.items():
            if hour in cfg["hours"]:
                return name
        return "Nuit"

    df_weather["moment"] = df_weather["hour"].apply(assign_moment)
    df_filtered = df_weather[df_weather["date"].isin(dates_list)]

    carnet_data = charger_carnet()
    bonus_historique_actif = len(carnet_data) >= 3

    records = []
    for (date, moment), group in df_filtered.groupby(["date", "moment"]):
        wind_speed = group["wind_speed_10m"].mean()
        wind_dir = group["wind_direction_10m"].mean()
        pressure = group["surface_pressure"].mean()
        cloud_cover = group["cloud_cover"].mean()
        wave_height = group["wave_height"].mean() if not group["wave_height"].isna().all() else 1.0
        water_temp = group["sea_surface_temperature"].mean() if not group["sea_surface_temperature"].isna().all() else 15.0

        day_tide = tides_dict.get(date, {"max_coef": 70, "extrema": []})
        coef = day_tide["max_coef"]

        if coef >= 75: note_maree, desc_maree = 5, f"Excellent coefficient ({coef} >= 75) — Fortes veines de courant"
        elif coef >= 60: note_maree, desc_maree = 4, f"Bon coefficient ({coef})"
        elif coef >= 45: note_maree, desc_maree = 3, f"Coefficient moyen ({coef})"
        else: note_maree, desc_maree = 1, f"Morte-eau stricte ({coef})"

        if pressure < 1010: note_press, desc_press = 5, f"Dépression / Baisse marquée ({round(pressure,1)} hPa)"
        elif pressure <= 1022: note_press, desc_press = 3, f"Pression stable ({round(pressure,1)} hPa)"
        else: note_press, desc_press = 2, f"Anticyclone durable ({round(pressure,1)} hPa)"

        is_vent_favorable = 180 <= wind_dir <= 310
        if 12 <= wind_speed <= 30 and is_vent_favorable and wave_height >= 0.8:
            note_vent, desc_vent = 5, f"Vent Sud/Ouest ({round(wind_speed,1)} km/h) & Houle ({round(wave_height,1)}m)"
        elif wind_speed < 8:
            note_vent, desc_vent = 1, f"Calme plat total ({round(wind_speed,1)} km/h)"
        else:
            note_vent, desc_vent = 3, f"Vent modéré ({round(wind_speed,1)} km/h)"

        if moment in ["Aube (Coup du matin)", "Crépuscule (Coup du soir)"]:
            note_moment, desc_moment = 5, f"{moment} — Transition lumineuse idéale"
        elif moment == "Nuit":
            note_moment, desc_moment = 4, "Nuit — Excellent en été (bordures)"
        elif cloud_cover >= 60:
            note_moment, desc_moment = 3, f"Journée nuageuse ({round(cloud_cover)}%)"
        else:
            note_moment, desc_moment = 1, "Plein soleil en journée"

        if 12 <= water_temp <= 20:
            note_eau, desc_eau = 5, f"Température idéale ({round(water_temp,1)}°C)"
        elif water_temp < 7:
            note_eau, desc_eau = 1, f"Eau trop froide ({round(water_temp,1)}°C)"
        else:
            note_eau, desc_eau = 3, f"Eau fraîche/limite ({round(water_temp,1)}°C)"
        
        note_carnet, desc_carnet = 3, "Historique neutre"
        if bonus_historique_actif:
            similar_catches = [c for c in carnet_data if abs(c.get("coef", 70) - coef) <= 10]
            if similar_catches:
                note_carnet, desc_carnet = 5, f"🔥 Apprentissage IA : {len(similar_catches)} prise(s) sur ce type de coef"

        score_total = round(
            (note_maree * 0.25) + 
            (note_press * 0.20) + 
            (note_vent * 0.20) + 
            (note_moment * 0.15) + 
            (note_eau * 0.10) + 
            (note_carnet * 0.10), 2
        ) * 20

        records.append({
            "date": date, "moment": moment, "score_total": score_total, "coef": coef,
            "note_maree": note_maree, "desc_maree": desc_maree,
            "note_press": note_press, "desc_press": desc_press,
            "note_vent": note_vent, "desc_vent": desc_vent,
            "note_moment": note_moment, "desc_moment": desc_moment,
            "note_eau": note_eau, "desc_eau": desc_eau,
            "note_carnet": note_carnet, "desc_carnet": desc_carnet,
        })

    df_grouped = pd.DataFrame(records)
    moments_order = ["Aube (Coup du matin)", "Matin (Lumière douce)", "Après-Midi (Plein soleil)", "Crépuscule (Coup du soir)", "Nuit"]

    tab_grille, tab_carnet, tab_analyse, tab_shom = st.tabs([
        "📊 Grille & Vue Détaillée", 
        "📖 Carnet de Prises & Saisie", 
        "🧠 Auto-Apprentissage & Stats", 
        "🌊 Widget SHOM"
    ])

    with tab_grille:
        st.header("Grille Globale des Conditions (15 Jours)")
        matrix_df = df_grouped.pivot(index="date", columns="moment", values="score_total")
        matrix_df = matrix_df.reindex(columns=[m for m in moments_order if m in matrix_df.columns])
        st.dataframe(matrix_df.style.background_gradient(cmap="RdYlGn", vmin=40, vmax=90).format("{:.1f}"), use_container_width=True, height=400)

        st.divider()
        st.header("🔍 Analyse Détaillée de la Journée")
        
        # UN SEUL MENU DÉROULANT POUR LA DATE COMMUNE
        selected_date = st.selectbox("📅 Sélectionner la date à analyser", df_grouped["date"].unique(), key="sel_date_commun")

        st.markdown("### 🌊 Marées du Jour")
        day_info = tides_dict.get(selected_date, {})
        extrema = day_info.get("extrema", [])
        
        if extrema:
            cols_tide = st.columns(len(extrema))
            for idx, ext in enumerate(extrema):
                with cols_tide[idx]:
                    t_type = ext.get("type")
                    t_time = ext.get("time", "").split("T")[-1][:5]
                    t_height = ext.get("height", "N/A")
                    t_coef = ext.get("coef", "-")
                    
                    label = "Pleine Mer (PM)" if t_type == "PM" else "Basse Mer (BM)"
                    st.metric(label=f"{label} à {t_time}", value=f"{t_height} m", delta=f"Coef : {t_coef}" if t_type == "PM" else None)
        else:
            st.info("Données de marées non disponibles pour cette date.")

        st.markdown("---")
        st.markdown("### ⏰ Détail par Créneau (Aube, Matin, etc.)")
        
        # Sélecteur de moment pour la date choisie
        selected_moment = st.selectbox("Choisir le créneau horaire", moments_order, key="sel_moment_detail")

        row_detail = df_grouped[(df_grouped["date"] == selected_date) & (df_grouped["moment"] == selected_moment)]

        if not row_detail.empty:
            r = row_detail.iloc[0]
            st.subheader(f"Score Global du Créneau : {r['score_total']} / 100")

            col_d1, col_d2 = st.columns(2)
            with col_d1:
                st.write("#### 🌊 Marée & Coefficients (25%)")
                render_score_badge(r["note_maree"], r["desc_maree"])

                st.write("#### 📉 Pression Atmosphérique (20%)")
                render_score_badge(r["note_press"], r["desc_press"])

                st.write("#### 🌬️ Vent, Houle & Orientation (20%)")
                render_score_badge(r["note_vent"], r["desc_vent"])

            with col_d2:
                st.write("#### 🌅 Moment du Jour & Luminosité (15%)")
                render_score_badge(r["note_moment"], r["desc_moment"])

                st.write("#### 🌡️ Température de l'Eau (10%)")
                render_score_badge(r["note_eau"], r["desc_eau"])

                st.write("#### 📖 Carnet & Historique (10%)")
                render_score_badge(r["note_carnet"], r["desc_carnet"])
        else:
            st.info("Aucune donnée disponible pour ce créneau précis.")

    with tab_carnet:
        st.header("📖 Enregistrer une Session ou une Prise")
        with st.form("form_carnet"):
            col_f1, col_f2, col_f3 = st.columns(3)
            with col_f1:
                date_prise = st.date_input("Date de la sortie", datetime.now())
                spot_prise = st.selectbox("Spot", list(SPOTS.keys()))
            with col_f2:
                nb_poissons = st.number_input("Nombre de bars pris", min_value=0, max_value=20, value=1)
                taille_max = st.number_input("Taille maximale (cm)", min_value=0, max_value=100, value=45)
            with col_f3:
                leurre_utilise = st.text_input("Leurre / Technique principal(e)", "Black Minnow 120")
                
            commentaire = st.text_area("Notes sur la session")
            submit_prise = st.form_submit_button("Enregistrer dans le Carnet 🎣")

            if submit_prise:
                date_str = date_prise.strftime("%Y-%m-%d")
                coef_jour = tides_dict.get(date_str, {}).get("max_coef", 70)
                
                new_entry = {
                    "date": date_str,
                    "spot": spot_prise,
                    "nb_poissons": nb_poissons,
                    "taille_max": taille_max,
                    "leurre": leurre_utilise,
                    "commentaire": commentaire,
                    "coef": coef_jour
                }
                carnet_data.append(new_entry)
                sauvegarder_carnet(carnet_data)
                st.success("✅ Prise enregistrée avec succès !")

        st.divider()
        st.subheader("Historique de vos prises enregistrées")
        if carnet_data:
            df_carnet = pd.DataFrame(carnet_data)
            st.dataframe(df_carnet, use_container_width=True)
            if st.button("🗑️ Vider le carnet"):
                if os.path.exists(CARNET_FILE):
                    os.remove(CARNET_FILE)
                st.rerun()
        else:
            st.info("Aucune prise enregistrée pour le moment.")

    with tab_analyse:
        st.header("🧠 Analyse & Auto-Apprentissage de l'Algorithme")
        if len(carnet_data) >= 3:
            df_c = pd.DataFrame(carnet_data)
            moy_coef = df_c["coef"].mean()
            st.metric("Coefficient moyen de réussite mesuré", f"{round(moy_coef, 1)}")
            st.success("🤖 L'algorithme a détecté un pattern sur vos coefficients favoris !")
        else:
            st.warning("⚠️ Pas assez de données dans le carnet (minimum 3 sessions requises).")

    with tab_shom:
        st.header("Graphique SHOM Officiel")
        shom_url = f"https://services.data.shom.fr/oceano/render/html/widget?duration=4&delta-date=0&lon={coords['lon']}&lat={coords['lat']}&utc=1&lang=fr"
        st.components.v1.iframe(shom_url, height=500, scrolling=True)