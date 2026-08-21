import streamlit as st
import requests
import pandas as pd
import json
import os
from datetime import datetime, timedelta
import math
from streamlit_folium import st_folium
import folium

st.set_page_config(page_title="Aide à la Décision - Pêche au Bar V4.2", layout="wide")

st.title("🎣 Aide à la Décision V4.2 — Pêche au Bar & Stations Dynamiques")
st.caption("Géolocalisation dynamique, couplage Météo/Marées & Carte des prises")

API_KEY_MAREE = "9452804b6f6e7a5204505c36d252ea48"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
CARNET_FILE = "carnet_peche.json"

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

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R * c

@st.cache_data(ttl=86400)
def charger_ports_api(api_key):
    url = f"https://api-maree.fr/sites?key={api_key}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            data = res.json()
            sites = data.get("sites", data if isinstance(data, list) else [])
            ports_propres = []
            for s in sites:
                s_id = s.get("site_id") or s.get("id") or s.get("code")
                s_name = s.get("site_name") or s.get("name") or s_id
                lat = s.get("latitude") or s.get("lat")
                lon = s.get("longitude") or s.get("lon")
                
                if s_id and lat is not None and lon is not None:
                    ports_propres.append({
                        "nom": str(s_name),
                        "lat": float(lat),
                        "lon": float(lon),
                        "site_maree": str(s_id)
                    })
            if ports_propres:
                return ports_propres
    except Exception:
        pass
    
    return [
        {"nom": "Le Croisic", "lat": 47.2931, "lon": -2.5204, "site_maree": "le-croisic"},
        {"nom": "Piriac-sur-Mer", "lat": 47.3781, "lon": -2.5512, "site_maree": "piriac-sur-mer"},
        {"nom": "Saint-Nazaire", "lat": 47.2300, "lon": -2.1800, "site_maree": "saint-nazaire"},
        {"nom": "Pornichet", "lat": 47.2625, "lon": -2.3361, "site_maree": "pornichet"}
    ]

REFERENCE_SITES = charger_ports_api(API_KEY_MAREE)

def trouver_station_la_plus_proche(lat, lon, liste_sites):
    plus_proche = liste_sites[0]
    min_dist = float('inf')
    for station in liste_sites:
        dist = haversine(lat, lon, station["lat"], station["lon"])
        if dist < min_dist:
            min_dist = dist
            plus_proche = station
    return plus_proche

# --- SÉLECTION DE LA ZONE SUR CARTE DANS LA SIDEBAR ---
st.sidebar.header("🗺️ Sélection de la Zone")
mode_selection = st.sidebar.radio("Méthode de ciblage", ["Carte interactive cliquable", "Recherche par nom de port"])

if mode_selection == "Recherche par nom de port":
    noms_tires = sorted([s["nom"] for s in REFERENCE_SITES])
    choix_defaut = st.sidebar.selectbox("Secteur / Port", noms_tires)
    station_active = next(s for s in REFERENCE_SITES if s["nom"] == choix_defaut)
    lat_cible, lon_cible = station_active["lat"], station_active["lon"]
else:
    st.sidebar.info("Cliquez sur la carte ci-dessous pour définir votre zone de pêche.")
    m_sel = folium.Map(location=[47.3, -2.5], zoom_start=10)
    m_sel.add_child(folium.LatLngPopup())
    map_data = st_folium(m_sel, height=250, width="100%", key="map_selector")
    
    if map_data and map_data.get("last_clicked"):
        lat_cible = map_data["last_clicked"]["lat"]
        lon_cible = map_data["last_clicked"]["lng"]
        st.sidebar.success(f"Position choisie : {round(lat_cible, 4)}, {round(lon_cible, 4)}")
    else:
        lat_cible, lon_cible = 47.2931, -2.5204

# Recherche automatique du port de marée le plus proche
station_proche = trouver_station_la_plus_proche(lat_cible, lon_cible, REFERENCE_SITES)

st.sidebar.divider()
st.sidebar.markdown(f"**📍 Zone Météo / Spot actif :**\n`Lat: {round(lat_cible, 4)}, Lon: {round(lon_cible, 4)}`")
st.sidebar.markdown(f"**🌊 Port de Marée rattaché :** {station_proche['nom']}")
st.sidebar.markdown(f"**Identifiant API Marée :** `{station_proche['site_maree']}`")

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
        
        days_array = []
        if isinstance(data, list):
            days_array = data
        elif isinstance(data, dict):
            days_array = data.get("data", data.get("days", []))

        for day in days_array:
            date_key = day.get("date") or day.get("day")
            if not date_key:
                continue
            date_key = str(date_key).split("T")[0]
            extrema = day.get("extrema", [])
            coefs = [e.get("coef", 0) for e in extrema if e.get("type") == "PM" and e.get("coef")]
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

df_weather = fetch_weather_16days(lat_cible, lon_cible)
df_marine = fetch_marine_data(lat_cible, lon_cible)

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
    tides_dict = fetch_tides_15days(station_proche["site_maree"], start_date, end_date)

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

        group_sorted = group.sort_values("time")
        first_time_val = group_sorted["time"].iloc[0]
        past_weather = df_weather[(df_weather["time"] >= first_time_val - timedelta(hours=6)) & (df_weather["time"] < first_time_val)]
        pressure_delta = pressure - past_weather["surface_pressure"].mean() if not past_weather.empty else 0.0

        day_info = tides_dict.get(date, {"max_coef": 70, "extrema": []})
        coef = day_info["max_coef"]
        extrema = day_info.get("extrema", [])

        mean_hour = group["hour"].mean()
        is_near_pm = False
        pm_info_str = ""
        for ext in extrema:
            if ext.get("type") == "PM":
                try:
                    pm_time_str = ext.get("time", "").split("T")[-1]
                    pm_hour = int(pm_time_str.split(":")[0]) + int(pm_time_str.split(":")[1])/60.0
                    if (pm_hour - 2.0) <= mean_hour <= (pm_hour + 1.0):
                        is_near_pm = True
                        pm_info_str = f" (Idéal : Pleine Mer à {pm_time_str[:5]})"
                        break
                except Exception:
                    pass

        if coef >= 75 and is_near_pm:
            note_maree, desc_maree = 5, f"Coef {coef} + Pleine Mer imminente/récente{pm_info_str}"
        elif coef >= 60 and is_near_pm:
            note_maree, desc_maree = 4, f"Bon coef ({coef}) dans la fenêtre clé PM{pm_info_str}"
        elif coef >= 75:
            note_maree, desc_maree = 4, f"Fort coefficient ({coef}) hors fenêtre PM"
        elif coef >= 60:
            note_maree, desc_maree = 3, f"Coefficient correct ({coef})"
        else:
            note_maree, desc_maree = 1, f"Morte-eau stricte ({coef})"

        if pressure < 1010 or pressure_delta < -1.0:
            note_press, desc_press = 5, f"Dépression / Baisse marquée ({round(pressure,1)} hPa)"
        elif pressure <= 1022 and pressure_delta <= -0.3:
            note_press, desc_press = 4, f"Pression en baisse favorable ({round(pressure,1)} hPa)"
        elif pressure <= 1022:
            note_press, desc_press = 3, f"Pression stable ({round(pressure,1)} hPa)"
        else:
            note_press, desc_press = 2, f"Anticyclone durable ({round(pressure,1)} hPa)"

        is_vent_favorable = 180 <= wind_dir <= 310
        if 12 <= wind_speed <= 30 and is_vent_favorable and wave_height >= 0.8:
            note_vent, desc_vent = 5, f"Vent SO ({round(wind_speed,1)} km/h) & Houle ({round(wave_height,1)}m)"
        elif wind_speed < 8:
            note_vent, desc_vent = 1, f"Calme plat ({round(wind_speed,1)} km/h)"
        else:
            note_vent, desc_vent = 3, f"Vent modéré ({round(wind_speed,1)} km/h)"

        if moment in ["Aube (Coup du matin)", "Crépuscule (Coup du soir)"]:
            note_moment, desc_moment = 5, f"{moment} — Transition lumineuse"
        elif moment == "Nuit":
            note_moment, desc_moment = 4, "Nuit — Excellent en été"
        elif cloud_cover >= 60:
            note_moment, desc_moment = 3, f"Nuageux ({round(cloud_cover)}%)"
        else:
            note_moment, desc_moment = 1, "Plein soleil"

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
                note_carnet, desc_carnet = 5, f"🔥 IA : {len(similar_catches)} prise(s) sur ce type de coef"

        score_total = round(
            (note_maree * 0.25) + (note_press * 0.20) + (note_vent * 0.20) + 
            (note_moment * 0.15) + (note_eau * 0.10) + (note_carnet * 0.10), 2
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
        "📖 Carnet, GPS & Carte des Prises", 
        "🧠 Auto-Apprentissage & Stats", 
        "🌊 Widget SHOM"
    ])

    with tab_grille:
        st.header(f"Grille Globale")
        st.caption(f"🎯 Données météo/vent basées sur le spot ({round(lat_cible, 4)}, {round(lon_cible, 4)}) — 🌊 Marées basées sur le port : **{station_proche['nom']}**")
        
        matrix_df = df_grouped.pivot(index="date", columns="moment", values="score_total")
        matrix_df = matrix_df.reindex(columns=[m for m in moments_order if m in matrix_df.columns])
        st.dataframe(matrix_df.style.background_gradient(cmap="RdYlGn", vmin=40, vmax=90).format("{:.1f}"), use_container_width=True, height=400)

        st.divider()
        st.header("🔍 Analyse Détaillée de la Journée")
        
        selected_date = st.selectbox("📅 Sélectionner la date à analyser", df_grouped["date"].unique(), key="sel_date_commun")

        st.markdown(f"### 🌊 Marées du Jour (Port de référence : {station_proche['nom']})")
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
            st.warning(f"⚠️ Données de marées indisponibles pour le port `{station_proche['nom']}` à la date du {selected_date}.")

        st.markdown("---")
        st.markdown(f"### ⏰ Détail par Créneau (Météo du spot & Marées {station_proche['nom']})")
        selected_moment = st.selectbox("Choisir le créneau horaire", moments_order, key="sel_moment_detail")

        row_detail = df_grouped[(df_grouped["date"] == selected_date) & (df_grouped["moment"] == selected_moment)]

        if not row_detail.empty:
            r = row_detail.iloc[0]
            st.subheader(f"Score Global du Créneau : {r['score_total']} / 100")

            col_d1, col_d2 = st.columns(2)
            with col_d1:
                st.write(f"#### 🌊 Marée & Coefficients (25%) [Port: {station_proche['nom']}]")
                render_score_badge(r["note_maree"], r["desc_maree"])
                st.write("#### 📉 Pression Atmosphérique (20%) [Spot Météo]")
                render_score_badge(r["note_press"], r["desc_press"])
                st.write("#### 🌬️ Vent, Houle & Orientation (20%) [Spot Météo]")
                render_score_badge(r["note_vent"], r["desc_vent"])
            with col_d2:
                st.write("#### 🌅 Moment du Jour (15%)")
                render_score_badge(r["note_moment"], r["desc_moment"])
                st.write("#### 🌡️ Température de l'Eau (10%) [Spot Météo]")
                render_score_badge(r["note_eau"], r["desc_eau"])
                st.write("#### 📖 Carnet & Historique (10%)")
                render_score_badge(r["note_carnet"], r["desc_carnet"])
        else:
            st.info("Aucune donnée disponible pour ce créneau précis.")

    with tab_carnet:
        st.header("📖 Enregistrer une Prise avec Localisation GPS")
        st.info("Astuce : Clique sur la carte ci-dessous pour positionner précisément le lieu exact de ta prise.")

        m_prise = folium.Map(location=[lat_cible, lon_cible], zoom_start=12)
        m_prise.add_child(folium.LatLngPopup())
        
        for c in carnet_data:
            if "lat" in c and "lon" in c:
                folium.Marker(
                    [c["lat"], c["lon"]],
                    popup=f"<b>{c['nb_poissons']} bar(s)</b><br>Taille max: {c['taille_max']}cm<br>Leurre: {c['leurre']}<br>Date: {c['date']}",
                    icon=folium.Icon(color="green", icon="fish", prefix="fa")
                ).add_to(m_prise)

        map_prise_data = st_folium(m_prise, height=350, width="100%", key="map_prise_click")

        default_lat = lat_cible
        default_lon = lon_cible
        if map_prise_data and map_prise_data.get("last_clicked"):
            default_lat = map_prise_data["last_clicked"]["lat"]
            default_lon = map_prise_data["last_clicked"]["lng"]

        with st.form("form_carnet"):
            col_f1, col_f2, col_f3 = st.columns(3)
            with col_f1:
                date_prise = st.date_input("Date de la sortie", datetime.now())
                lat_saisi = st.number_input("Latitude", value=float(default_lat), format="%.5f")
            with col_f2:
                nb_poissons = st.number_input("Nombre de bars pris", min_value=0, max_value=20, value=1)
                lon_saisi = st.number_input("Longitude", value=float(default_lon), format="%.5f")
            with col_f3:
                taille_max = st.number_input("Taille maximale (cm)", min_value=0, max_value=100, value=45)
                leurre_utilise = st.text_input("Leurre / Technique", "Black Minnow 120")
                
            commentaire = st.text_area("Notes sur la session (postes, conditions...)")
            submit_prise = st.form_submit_button("Enregistrer la prise avec GPS 🎣")

            if submit_prise:
                date_str = date_prise.strftime("%Y-%m-%d")
                coef_jour = tides_dict.get(date_str, {}).get("max_coef", 70)
                
                new_entry = {
                    "date": date_str, "lat": lat_saisi, "lon": lon_saisi,
                    "nb_poissons": nb_poissons, "taille_max": taille_max,
                    "leurre": leurre_utilise, "commentaire": commentaire, "coef": coef_jour
                }
                carnet_data.append(new_entry)
                sauvegarder_carnet(carnet_data)
                st.success("✅ Prise enregistrée et géolocalisée avec succès !")

        st.divider()
        st.subheader("📋 Historique tabulaire des prises")
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
        st.caption(f"Affichage centré sur les coordonnées du spot : {round(lat_cible, 4)}, {round(lon_cible, 4)}")
        shom_url = f"https://services.data.shom.fr/oceano/render/html/widget?duration=4&delta-date=0&lon={lon_cible}&lat={lat_cible}&utc=1&lang=fr"
        st.components.v1.iframe(shom_url, height=500, scrolling=True)