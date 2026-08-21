import streamlit as st
import requests
import pandas as pd

st.set_page_config(page_title="Aide à la Décision - Pêche au Bar V3+", layout="wide")

st.title("🎣 Aide à la Décision V3+ — Pêche au Bar")
st.caption("Zone 50km Le Croisic & Côte Sauvage | Analyse Météo & Marées Réelles sur 15 Jours")

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
    "Aube (Coup du matin)": {"hours": range(5, 8), "weight": 95},
    "Matin (Lumière douce)": {"hours": range(8, 13), "weight": 65},
    "Après-Midi (Plein soleil)": {"hours": range(13, 18), "weight": 48},
    "Crépuscule (Coup du soir)": {"hours": range(18, 22), "weight": 90},
    "Nuit": {"hours": [22, 23, 0, 1, 2, 3, 4], "weight": 78}
}

spot_nom = st.sidebar.selectbox("📍 Secteur de pêche", list(SPOTS.keys()))
coords = SPOTS[spot_nom]

# 1. Météo sur 16 Jours via Open-Meteo
@st.cache_data(ttl=3600)
def fetch_weather_16days(lat, lon):
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m,surface_pressure,wind_speed_10m,wind_direction_10m&forecast_days=16&timezone=auto"
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

# 2. Marée Réelle sur 15 Jours via api-maree.fr
@st.cache_data(ttl=3600)
def fetch_tides_15days(site_slug, start_date, end_date):
    url = f"https://api-maree.fr/tide-extrema?site={site_slug}&from={start_date}&to={end_date}&tz=Europe/Paris&key={API_KEY_MAREE}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            st.error(f"❌ Échec API Marée (Code {res.status_code}) : {res.text}")
            return {}
        
        data = res.json()
        tides_by_date = {}
        
        if "data" in data:
            for day in data["data"]:
                date_key = day.get("date")
                extrema = day.get("extrema", [])
                
                # Extraire tous les coefficients (présents sur PM)
                coefs = [e["coef"] for e in extrema if e.get("type") == "PM" and "coef" in e]
                max_coef = max(coefs) if coefs else 70
                
                tides_by_date[date_key] = {
                    "max_coef": max_coef,
                    "extrema": extrema
                }
        return tides_by_date
    except Exception as e:
        st.error(f"❌ Erreur de connexion vers api-maree.fr : {e}")
        return {}

df_weather = fetch_weather_16days(coords["lat"], coords["lon"])

if not df_weather.empty:
    df_weather["date"] = df_weather["time"].dt.strftime("%Y-%m-%d")
    df_weather["hour"] = df_weather["time"].dt.hour

    dates_list = sorted(df_weather["date"].unique())[:15]
    start_date, end_date = dates_list[0], dates_list[-1]

    # Récupération globale des marées pour les 15 jours
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

        # Marée réelle du jour
        day_tide = tides_dict.get(date, {"max_coef": 70, "extrema": []})
        coef = day_tide["max_coef"]

        # Sub-scores
        sub_moment = MOMENTS_MAP[moment]["weight"]
        is_vent_mer = 200 <= wind_dir <= 290
        sub_vent = 90 if (12 <= wind_speed <= 25 and is_vent_mer) else 55
        sub_pression = 85 if pressure < 1015 else 60
        sub_maree = 90 if coef >= 80 else (75 if coef >= 55 else 50)

        # Pondération globale
        score_total = round(
            (0.30 * sub_maree) + 
            (0.30 * sub_moment) + 
            (0.25 * sub_vent) + 
            (0.15 * sub_pression), 1
        )

        records.append({
            "date": date,
            "moment": moment,
            "score_total": score_total,
            "coef": coef,
            "wind_speed": wind_speed,
            "wind_dir": wind_dir,
            "pressure": pressure
        })

    df_grouped = pd.DataFrame(records)

    # 1. Grille sur 15 Jours
    st.header("1. Grille des Conditions Globale (15 Jours)")
    moments_order = ["Aube (Coup du matin)", "Matin (Lumière douce)", "Après-Midi (Plein soleil)", "Crépuscule (Coup du soir)", "Nuit"]
    matrix_df = df_grouped.pivot(index="date", columns="moment", values="score_total")
    matrix_df = matrix_df.reindex(columns=[m for m in moments_order if m in matrix_df.columns])

    st.dataframe(
        matrix_df.style.background_gradient(cmap="RdYlGn", vmin=40, vmax=90).format("{:.1f}"),
        use_container_width=True,
        height=500
    )

    # 2. Vue Détaillée
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
            st.metric(label=f"Score Global ({selected_date} — {selected_moment[:4]})", value=f"{r['score_total']} / 100")
            st.write(f"**Vent moyen** : {round(r['wind_speed'], 1)} km/h ({round(r['wind_dir'])}°)")
            st.write(f"**Pression** : {round(r['pressure'], 1)} hPa")

        with col_m2:
            st.subheader("🌊 Informations Marée Réelle")
            day_tide_info = tides_dict.get(selected_date, {})
            
            if day_tide_info and "extrema" in day_tide_info:
                st.write(f"**Coefficient max du jour** : **{day_tide_info['max_coef']}**")
                st.write("**Étales du jour :**")
                for e in day_tide_info["extrema"]:
                    t_label = "Pleine Mer (PM)" if e["type"] == "PM" else "Basse Mer (BM)"
                    c_label = f" — Coef {e['coef']}" if "coef" in e else ""
                    st.write(f"- **{t_label}** à {e['time']} ({round(e['height'], 2)} m){c_label}")
            else:
                st.warning("Données de marée non disponibles pour cette date.")

# 3. Widget SHOM
st.divider()
st.header("3. Graphique SHOM Officiel")
shom_url = f"https://services.data.shom.fr/oceano/render/html/widget?duration=4&delta-date=0&lon={coords['lon']}&lat={coords['lat']}&utc=1&lang=fr"
st.components.v1.iframe(shom_url, height=500, scrolling=True)