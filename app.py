import streamlit as st
import requests
import pandas as pd

st.set_page_config(page_title="Aide à la Décision - Pêche au Bar V3+", layout="wide")

st.title("🎣 Aide à la Décision V3+ — Pêche au Bar")
st.caption("Zone 50km Le Croisic & Côte Sauvage | Algorithme Calibré & Données Réelles")

API_KEY_MAREE = "9452804b6f6e7a5204505c36d252ea48"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

SPOTS = {
    "Côte Sauvage (Le Croisic)": {"lat": 47.2931, "lon": -2.5204, "site": "le-croisic"},
    "Pointe du Castelli (Piriac)": {"lat": 47.3781, "lon": -2.5512, "site": "piriac-sur-mer"},
    "Baie de Mesquer": {"lat": 47.3986, "lon": -2.4635, "site": "piriac-sur-mer"},
    "Estuaire de la Loire": {"lat": 47.2300, "lon": -2.1800, "site": "saint-nazaire"},
    "Île de Dumet": {"lat": 47.4111, "lon": -2.6208, "site": "piriac-sur-mer"}
}

MOMENTS_MAP = {
    "Aube (Coup du matin)": {"hours": range(5, 8), "weight": 5},
    "Matin (Lumière douce)": {"hours": range(8, 13), "weight": 3},
    "Après-Midi (Plein soleil)": {"hours": range(13, 18), "weight": 2},
    "Crépuscule (Coup du soir)": {"hours": range(18, 22), "weight": 5},
    "Nuit": {"hours": [22, 23, 0, 1, 2, 3, 4], "weight": 4}
}

spot_nom = st.sidebar.selectbox("📍 Secteur de pêche", list(SPOTS.keys()))
coords = SPOTS[spot_nom]

# 1. API Météo Standard (Air, Vent, Pression, Nuages)
@st.cache_data(ttl=3600)
def fetch_weather_16days(lat, lon):
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m,surface_pressure,wind_speed_10m,wind_direction_10m,cloud_cover&forecast_days=16&timezone=auto"
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

# 2. API Marine Officielle (Houle & Température de l'eau exacte)
@st.cache_data(ttl=3600)
def fetch_marine_data(lat, lon):
    url = f"https://marine-api.open-meteo.com/v1/marine?latitude={lat}&longitude={lon}&hourly=wave_height,sea_surface_temperature&forecast_days=7&timezone=auto"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            return pd.DataFrame()
        df = pd.DataFrame(res.json()["hourly"])
        df["time"] = pd.to_datetime(df["time"])
        return df
    except Exception:
        return pd.DataFrame()

# 3. API Marée Réelle
@st.cache_data(ttl=3600)
def fetch_tides_15days(site_slug, start_date, end_date):
    url = f"https://api-maree.fr/tide-extrema?site={site_slug}&from={start_date}&to={end_date}&tz=Europe/Paris&key={API_KEY_MAREE}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            return {}
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

    records = []
    for (date, moment), group in df_filtered.groupby(["date", "moment"]):
        wind_speed = group["wind_speed_10m"].mean()
        wind_dir = group["wind_direction_10m"].mean()
        pressure = group["surface_pressure"].mean()
        cloud_cover = group["cloud_cover"].mean()
        wave_height = group["wave_height"].mean() if "wave_height" in group and not group["wave_height"].isna().all() else 1.0
        water_temp = group["sea_surface_temperature"].mean() if "sea_surface_temperature" in group and not group["sea_surface_temperature"].isna().all() else 15.0

        day_tide = tides_dict.get(date, {"max_coef": 70, "extrema": []})
        coef = day_tide["max_coef"]

        # --- 1. Marée & Coefficients (25%) ---
        if coef >= 75: note_maree, desc_maree = 5, f"Excellent coefficient ({coef} >= 75) — Fortes veines de courant"
        elif coef >= 60: note_maree, desc_maree = 4, f"Bon coefficient ({coef}) — Activité correcte"
        elif coef >= 45: note_maree, desc_maree = 3, f"Coefficient moyen ({coef})"
        elif coef >= 35: note_maree, desc_maree = 2, f"Faible coefficient ({coef})"
        else: note_maree, desc_maree = 1, f"Morte-eau stricte ({coef}) — Absence de courant"

        # --- 2. Pression Atmosphérique (20%) ---
        if pressure < 1010: note_press, desc_press = 5, f"Dépression / Baisse marquée ({round(pressure,1)} hPa) — Idéal"
        elif pressure < 1015: note_press, desc_press = 4, f"Pression favorable ({round(pressure,1)} hPa)"
        elif pressure <= 1022: note_press, desc_press = 3, f"Pression stable ({round(pressure,1)} hPa)"
        else: note_press, desc_press = 2, f"Anticyclone durable ({round(pressure,1)} hPa) — Plus difficile"

        # --- 3. Vent, Houle & Orientation (20%) ---
        is_vent_favorable = 180 <= wind_dir <= 310  # Secteur Sud à Nord-Ouest
        if 12 <= wind_speed <= 30 and is_vent_favorable and wave_height >= 0.8:
            note_vent, desc_vent = 5, f"Vent Sud/Ouest ({round(wind_speed,1)} km/h) & Houle ({round(wave_height,1)}m) — Parfait"
        elif 10 <= wind_speed <= 35:
            note_vent, desc_vent = 4, f"Vent modéré ({round(wind_speed,1)} km/h)"
        elif wind_speed < 8:
            note_vent, desc_vent = 1, f"Calme plat total ({round(wind_speed,1)} km/h) / Eaux trop claires"
        else:
            note_vent, desc_vent = 2, f"Vent excessif ou secteur Nord/Est"

        # --- 4. Moment du Jour & Luminosité (15%) ---
        if moment in ["Aube (Coup du matin)", "Crépuscule (Coup du soir)"]:
            note_moment, desc_moment = 5, f"{moment} — Transition lumineuse idéale"
        elif moment == "Nuit":
            note_moment, desc_moment = 4, "Nuit — Excellent en été (bordures et abris)"
        elif cloud_cover >= 60:
            note_moment, desc_moment = 3, f"Journée nuageuse ({round(cloud_cover)}%)"
        else:
            note_moment, desc_moment = 1, f"Plein soleil en journée — Conditions difficiles"

        # --- 5. Température de l'Eau (10%) ---
        if 12 <= water_temp <= 20:
            note_eau, desc_eau = 5, f"Température idéale ({round(water_temp,1)}°C)"
        elif 7 <= water_temp < 12:
            note_eau, desc_eau = 3, f"Eau fraîche / limite ({round(water_temp,1)}°C)"
        elif water_temp < 7:
            note_eau, desc_eau = 1, f"Eau trop froide ({round(water_temp,1)}°C) — Inactivité"
        else:
            note_eau, desc_eau = 4, f"Eau chaude ({round(water_temp,1)}°C) — Prévoir profondeur"

        # --- 6. Carnet & Historique (10%) ---
        note_carnet, desc_carnet = 3, "Historique neutre (En attente de vos saisies)"

        # Calcul du score global pondéré exact (Somme des poids = 100%)
        score_total = round(
            (note_maree * 0.25) + 
            (note_press * 0.20) + 
            (note_vent * 0.20) + 
            (note_moment * 0.15) + 
            (note_eau * 0.10) + 
            (note_carnet * 0.10), 2
        ) * 20  # Remise sur 100 (Max 5 * 20 = 100)

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

    # 1. Grille sur 15 Jours
    st.header("1. Grille des Conditions Globale (15 Jours)")
    moments_order = ["Aube (Coup du matin)", "Matin (Lumière douce)", "Après-Midi (Plein soleil)", "Crépuscule (Coup du soir)", "Nuit"]
    matrix_df = df_grouped.pivot(index="date", columns="moment", values="score_total")
    matrix_df = matrix_df.reindex(columns=[m for m in moments_order if m in matrix_df.columns])

    st.dataframe(
        matrix_df.style.background_gradient(cmap="RdYlGn", vmin=40, vmax=90).format("{:.1f}"),
        use_container_width=True, height=500
    )

    # 2. Vue Détaillée
    st.divider()
    st.header("2. Analyse Détaillée par Critères")

    col_sel1, col_sel2 = st.columns(2)
    with col_sel1:
        selected_date = st.selectbox("Sélectionner la date", df_grouped["date"].unique())
    with col_sel2:
        selected_moment = st.selectbox("Sélectionner le créneau", moments_order)

    row_detail = df_grouped[(df_grouped["date"] == selected_date) & (df_grouped["moment"] == selected_moment)]

    if not row_detail.empty:
        r = row_detail.iloc[0]
        st.subheader(f"Score Global du Créneau : {r['score_total']} / 100")

        col_c1, col_c2 = st.columns(2)

        with col_c1:
            st.write("#### 🌊 Marée & Coefficients (25%)")
            render_score_badge(r["note_maree"], r["desc_maree"])

            st.write("#### 📉 Pression Atmosphérique (20%)")
            render_score_badge(r["note_press"], r["desc_press"])

            st.write("#### 🌬️ Vent, Houle & Orientation (20%)")
            render_score_badge(r["note_vent"], r["desc_vent"])

            st.write("#### 🌅 Moment du Jour & Luminosité (15%)")
            render_score_badge(r["note_moment"], r["desc_moment"])

            st.write("#### 🌡️ Température de l'Eau (10%)")
            render_score_badge(r["note_eau"], r["desc_eau"])

            st.write("#### 📖 Carnet & Historique (10%)")
            render_score_badge(r["note_carnet"], r["desc_carnet"])

        with col_c2:
            st.subheader("🌊 Horaires Marée Réelle")
            day_tide_info = tides_dict.get(selected_date, {})
            if day_tide_info and "extrema" in day_tide_info:
                st.write(f"**Coefficient max du jour** : **{day_tide_info['max_coef']}**")
                st.write("**Étales réelles :**")
                for e in day_tide_info["extrema"]:
                    t_label = "Pleine Mer (PM)" if e["type"] == "PM" else "Basse Mer (BM)"
                    c_label = f" — Coef {e['coef']}" if "coef" in e else ""
                    st.write(f"- **{t_label}** à {e['time']} ({round(e['height'], 2)} m){c_label}")
            else:
                st.warning("Données de marée non disponibles.")

# 3. Widget SHOM
st.divider()
st.header("3. Graphique SHOM Officiel")
shom_url = f"https://services.data.shom.fr/oceano/render/html/widget?duration=4&delta-date=0&lon={coords['lon']}&lat={coords['lat']}&utc=1&lang=fr"
st.components.v1.iframe(shom_url, height=500, scrolling=True)