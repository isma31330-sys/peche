import streamlit as st
import requests
import pandas as pd
import json
import os
from datetime import datetime, timedelta, date
import math
from urllib.parse import quote
from streamlit_folium import st_folium
import folium

# ============================================================
# AIDE À LA DÉCISION PÊCHE V5
# Bar & Daurade royale - Le Croisic / Sud Bretagne
#
# V5 :
# - profils espèce + technique
# - 10 spots préconfigurés autour du Croisic (~20 km)
# - météo 16 j
# - météo marine : houle, direction, période, SST, courant
# - marées api-maree.fr
# - phase de marée continue
# - pression dynamique
# - température eau + évolution
# - score spécifique au spot / espèce / technique
# - score de confiance
# - recommandation automatique du meilleur créneau
# - carnet de SESSIONS : succès et bredouilles
# - statistiques personnelles
#
# IMPORTANT :
# - Le courant Open-Meteo est une estimation modèle et ne remplace
#   pas les données locales SHOM. Open-Meteo signale lui-même une
#   précision limitée en zone côtière.
# - Les coordonnées des spots sont des points de départ
#   approximatifs : vérifier accès, réglementation, concessions,
#   réserves et sécurité avant de pêcher.
# ============================================================

st.set_page_config(
    page_title="Indice Pêche V5 — Bar & Daurade",
    page_icon="🎣",
    layout="wide",
)

# -----------------------------
# Configuration
# -----------------------------
HEADERS = {"User-Agent": "IndicePecheV5/1.0"}
CARNET_FILE = "carnet_peche_v5.json"

# Ne pas laisser une clé API en clair dans le code.
# Streamlit Cloud : Settings > Secrets
API_KEY_MAREE = st.secrets.get("API_KEY_MAREE", os.getenv("API_KEY_MAREE", ""))

CENTER = {"lat": 47.2931, "lon": -2.5204, "nom": "Le Croisic"}

# 10 secteurs de prospection autour du Croisic.
# Coordonnées volontairement approximatives.
SPOTS = [
    {
        "id": "croisic_cote_sauvage",
        "nom": "Pointe du Croisic / Côte sauvage",
        "lat": 47.2848, "lon": -2.5450,
        "fond": "Roche + sable / cassures",
        "orientation": 300,
        "exposition": "Ouest / Nord-Ouest",
        "bar": 9, "daurade": 8,
        "notes": "Pointes rocheuses, ressac, bordures de courant.",
        "techniques_bar": "Leurres souples 20–35 g, minnow, métal",
        "techniques_daurade": "Crabe, couteau, ver",
    },
    {
        "id": "port_lin",
        "nom": "Port Lin / Castouillet",
        "lat": 47.2745, "lon": -2.5235,
        "fond": "Roche + sable",
        "orientation": 270,
        "exposition": "Ouest",
        "bar": 8, "daurade": 8,
        "notes": "Zone mixte à prospecter autour des cassures et pointes.",
        "techniques_bar": "Leurre souple 15–30 g, petit jerkbait",
        "techniques_daurade": "Crabe / couteau, plomb 50–70 g",
    },
    {
        "id": "penchateau",
        "nom": "Pointe de Penchâteau — La Baule",
        "lat": 47.2560, "lon": -2.4260,
        "fond": "Roche + sable",
        "orientation": 260,
        "exposition": "Ouest / Sud-Ouest",
        "bar": 9, "daurade": 8,
        "notes": "Pointe exposée : rechercher les bordures de courant.",
        "techniques_bar": "Leurre souple 20–40 g, surface par faible houle",
        "techniques_daurade": "Crabe / couteau, 60–80 g",
    },
    {
        "id": "govelle",
        "nom": "La Govelle / rochers",
        "lat": 47.2630, "lon": -2.4340,
        "fond": "Sable + rochers",
        "orientation": 250,
        "exposition": "Ouest / Sud-Ouest",
        "bar": 8, "daurade": 7,
        "notes": "Fond mixte ; privilégier les transitions roche/sable.",
        "techniques_bar": "Leurre souple 15–30 g",
        "techniques_daurade": "Surfcasting léger, couteau / ver",
    },
    {
        "id": "turballe_musoir",
        "nom": "La Turballe — digue / musoir",
        "lat": 47.3465, "lon": -2.5120,
        "fond": "Enrochements + sable",
        "orientation": 270,
        "exposition": "Ouest",
        "bar": 8, "daurade": 8,
        "notes": "Digue et courant ; prudence sur les rochers humides.",
        "techniques_bar": "Leurre souple 20–40 g / métal",
        "techniques_daurade": "Crabe / couteau, coulissant 50–80 g",
    },
    {
        "id": "turballe_port",
        "nom": "La Turballe — secteur port / Port Creux",
        "lat": 47.3485, "lon": -2.5070,
        "fond": "Roche + sable",
        "orientation": 300,
        "exposition": "Nord-Ouest",
        "bar": 8, "daurade": 7,
        "notes": "Zone plus abritée ; intéressante quand la côte est trop exposée.",
        "techniques_bar": "Leurres souples 15–30 g",
        "techniques_daurade": "Crabe / couteau",
    },
    {
        "id": "piriac_castelli",
        "nom": "Piriac — Pointe de Castelli",
        "lat": 47.3790, "lon": -2.5445,
        "fond": "Roche + sable",
        "orientation": 270,
        "exposition": "Ouest",
        "bar": 9, "daurade": 8,
        "notes": "Pointe rocheuse ; chercher contre-courants et transitions.",
        "techniques_bar": "Leurre souple 20–35 g, jerkbait",
        "techniques_daurade": "Crabe, 60–80 g, fluoro 40–45/100",
    },
    {
        "id": "piriac_grillades",
        "nom": "Piriac — Les Grillades",
        "lat": 47.3815, "lon": -2.5500,
        "fond": "Dalles rocheuses + sable",
        "orientation": 270,
        "exposition": "Ouest",
        "bar": 8, "daurade": 8,
        "notes": "Fond mixte favorable aux poissons fourrage et coquillages.",
        "techniques_bar": "Leurre souple / petit jerkbait",
        "techniques_daurade": "Crabe / ver",
    },
    {
        "id": "mesquer_kercabellec",
        "nom": "Mesquer — Kercabellec",
        "lat": 47.3970, "lon": -2.4630,
        "fond": "Sable / vase + coquillages",
        "orientation": 180,
        "exposition": "Est / Sud-Est",
        "bar": 7, "daurade": 9,
        "notes": "Zone plus abritée ; fonds coquilliers et courant de chenal.",
        "techniques_bar": "Leurre souple léger, petit leurre",
        "techniques_daurade": "Crabe / couteau, 50–70 g",
    },
    {
        "id": "penbron_traict",
        "nom": "Pen-Bron — entrée du Traict",
        "lat": 47.3420, "lon": -2.5100,
        "fond": "Sable + coquillages + courant",
        "orientation": 210,
        "exposition": "Sud-Ouest",
        "bar": 8, "daurade": 9,
        "notes": "Chercher les lisières de courant et zones de ralentissement.",
        "techniques_bar": "Leurre souple 15–30 g",
        "techniques_daurade": "Coulissant 50–80 g, crabe / couteau",
    },
]

SPOT_BY_ID = {s["id"]: s for s in SPOTS}

SPECIES = {
    "Bar": {
        "emoji": "🐟",
        "techniques": [
            "Lancer-ramener / leurres souples",
            "Jerkbait / minnow",
            "Surface",
            "Métal",
        ],
        # poids : marée/courant/vent/houle/lumière/eau/pression/historique
        "weights": {
            "maree": 0.17,
            "courant": 0.18,
            "vent": 0.11,
            "houle": 0.10,
            "lumiere": 0.11,
            "eau": 0.10,
            "pression": 0.08,
            "historique": 0.10,
            "spot": 0.05,
        },
    },
    "Daurade royale": {
        "emoji": "🐠",
        "techniques": [
            "Crabe au posé",
            "Couteau / coquillage",
            "Ver",
            "Surfcasting",
        ],
        "weights": {
            "maree": 0.17,
            "courant": 0.19,
            "vent": 0.07,
            "houle": 0.08,
            "lumiere": 0.05,
            "eau": 0.10,
            "pression": 0.07,
            "historique": 0.12,
            "spot": 0.15,
        },
    },
}

# -----------------------------
# Utilitaires
# -----------------------------
def safe_float(v, default=None):
    try:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return default
        return float(v)
    except Exception:
        return default


def clamp(x, lo=0.0, hi=10.0):
    return max(lo, min(hi, float(x)))


def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


def circular_diff_deg(a, b):
    """Différence angulaire absolue entre 0 et 180 degrés."""
    return abs((a - b + 180) % 360 - 180)


def wind_to_score(wind_kmh, wind_dir, species):
    if wind_kmh is None:
        return 5.0, "Vent indisponible"

    # Modèle générique : on évite les règles binaires de V4.5.
    if species == "Bar":
        # Léger/modéré généralement confortable au leurre.
        if 10 <= wind_kmh <= 28:
            base = 8.5
        elif 6 <= wind_kmh < 10:
            base = 6.5
        elif 28 < wind_kmh <= 38:
            base = 6.0
        elif wind_kmh < 6:
            base = 4.5
        else:
            base = 2.0
    else:
        # Daurade au posé : trop de vent pénalise surtout le confort et la tenue.
        if 5 <= wind_kmh <= 25:
            base = 8.0
        elif 25 < wind_kmh <= 32:
            base = 6.0
        elif wind_kmh < 5:
            base = 6.0
        else:
            base = 2.5

    return clamp(base), f"{wind_kmh:.1f} km/h"


def wave_score(wave_h, wave_period, species, spot):
    if wave_h is None:
        return 5.0, "Houle indisponible"

    period = wave_period or 7.0

    if species == "Bar":
        # Un peu de mer peut être favorable, mais trop de houle dégrade
        # la lisibilité et la sécurité du lancer.
        if 0.5 <= wave_h <= 1.5:
            s = 9.0
        elif 0.2 <= wave_h < 0.5:
            s = 7.0
        elif 1.5 < wave_h <= 2.2:
            s = 6.5
        elif wave_h < 0.2:
            s = 5.0
        else:
            s = 2.0
        if period >= 10 and wave_h >= 0.8:
            s += 0.5
    else:
        # Daurade : mer légèrement formée possible, mais éviter le gros clapot.
        if 0.3 <= wave_h <= 1.2:
            s = 8.5
        elif 0.1 <= wave_h < 0.3:
            s = 7.0
        elif 1.2 < wave_h <= 1.8:
            s = 6.0
        elif wave_h < 0.1:
            s = 5.5
        else:
            s = 2.5

    return clamp(s), f"{wave_h:.1f} m / {period:.1f} s"


def pressure_score(pressure, d3, d6, d12):
    if pressure is None:
        return 5.0, "Pression indisponible"

    # La dynamique compte plus que la valeur absolue.
    trend = d6 if d6 is not None else (d3 if d3 is not None else 0.0)

    if trend <= -4:
        s = 9.0
        label = "Forte baisse"
    elif trend <= -2:
        s = 8.0
        label = "Baisse nette"
    elif trend <= -0.7:
        s = 7.0
        label = "Baisse modérée"
    elif trend < 0.7:
        s = 6.0
        label = "Stable"
    elif trend < 2:
        s = 5.0
        label = "Hausse modérée"
    else:
        s = 4.0
        label = "Hausse nette"

    # Une pression extrême n'est pas automatiquement "mauvaise".
    if pressure < 1005:
        s -= 0.5
    elif pressure > 1030:
        s -= 0.5

    return clamp(s), f"{pressure:.1f} hPa — {label} ({trend:+.1f} hPa/6h)"


def water_score(sst, delta24=None, species="Bar"):
    if sst is None:
        return 5.0, "SST indisponible"

    # Zone souple : on récompense surtout la cohérence saisonnière et les
    # variations modérées. Ce n'est pas une loi biologique universelle.
    if species == "Bar":
        if 11 <= sst <= 19:
            s = 8.5
        elif 9 <= sst < 11 or 19 < sst <= 21:
            s = 7.0
        elif 7 <= sst < 9 or 21 < sst <= 23:
            s = 5.0
        else:
            s = 3.0
    else:
        if 14 <= sst <= 21:
            s = 8.5
        elif 12 <= sst < 14 or 21 < sst <= 23:
            s = 7.0
        elif 10 <= sst < 12:
            s = 5.0
        else:
            s = 3.0

    # Un changement modéré de température peut signaler une arrivée d'eau.
    if delta24 is not None:
        if 0.3 <= abs(delta24) <= 1.5:
            s += 0.7
        elif abs(delta24) > 2.0:
            s -= 0.8

    return clamp(s), f"{sst:.1f} °C" + (
        f" ({delta24:+.1f} °C/24h)" if delta24 is not None else ""
    )


def light_score(dt_local, cloud, species):
    hour = dt_local.hour + dt_local.minute / 60
    transition = (
        (5.0 <= hour <= 8.5)
        or (18.0 <= hour <= 22.5)
    )

    if species == "Bar":
        if transition:
            base = 9.5
        elif 9 <= hour <= 17:
            base = 5.5
        else:
            base = 7.5
    else:
        # Lumière moins déterminante pour la daurade au posé.
        if transition:
            base = 7.5
        elif 9 <= hour <= 17:
            base = 6.0
        else:
            base = 6.5

    if cloud is not None:
        if 20 <= cloud <= 70:
            base += 0.5
        elif cloud > 90:
            base -= 0.3

    return clamp(base), "Transition lumineuse" if transition else "Lumière standard"


def continuous_coef_score(coef, species):
    if coef is None:
        return 5.0
    c = float(coef)

    if species == "Daurade royale":
        # Favorise les coefficients moyens à forts sans rupture artificielle.
        # Maximum indicatif autour de 90.
        return clamp(10 - abs(c - 90) / 12)
    else:
        # Bar : courant utile mais éviter de considérer les très gros coeffs
        # automatiquement meilleurs.
        return clamp(10 - abs(c - 78) / 16)


def parse_extreme_datetime(ext):
    t = ext.get("time")
    if not t:
        return None
    try:
        dt = pd.to_datetime(t)
        if pd.isna(dt):
            return None
        if getattr(dt, "tzinfo", None) is None:
            return dt.tz_localize("Europe/Paris")
        return dt
    except Exception:
        return None


def tide_phase_score(dt, extrema, species):
    """Retourne score, description, phase, distance au dernier événement."""
    if not extrema:
        return 5.0, "Marée indisponible", "Inconnue", None

    events = []
    for e in extrema:
        edt = parse_extreme_datetime(e)
        if edt is not None:
            events.append((edt, e.get("type", "")))

    if not events:
        return 5.0, "Marée indisponible", "Inconnue", None

    events.sort(key=lambda x: x[0])
    prev = None
    nxt = None
    for event in events:
        if event[0] <= dt:
            prev = event
        elif event[0] > dt and nxt is None:
            nxt = event

    if prev is None or nxt is None:
        return 5.0, "Phase incomplète", "Inconnue", None

    duration = (nxt[0] - prev[0]).total_seconds() / 3600
    elapsed = (dt - prev[0]).total_seconds() / 3600
    frac = max(0.0, min(1.0, elapsed / duration if duration else 0.5))

    # prev/nxt types :
    # BM -> PM : montant
    # PM -> BM : descendant
    rising = prev[1] == "BM" and nxt[1] == "PM"

    if rising:
        phase = "Montante"
        # Bar : souvent très intéressant sur le flot, surtout avant PM.
        # Daurade : privilégie ici les dernières heures du montant.
        if species == "Bar":
            s = 6 + 4 * frac
        else:
            s = 5 + 5 * frac
    else:
        phase = "Descendante"
        if species == "Bar":
            # Descendante peut rester productive ; moins forte par défaut.
            s = 8 - 3 * frac
        else:
            s = 7 - 3 * frac

    minutes_to_next = (nxt[0] - dt).total_seconds() / 60
    if minutes_to_next <= 90:
        s += 0.5

    return clamp(s), f"{phase} — prochaine {nxt[1]} à {nxt[0].strftime('%H:%M')}", phase, minutes_to_next


def historical_score(carnet, spot_id, species, technique, coef, dt):
    """Score basé sur les sessions, succès ET bredouilles.
    Retourne score, confiance historique, texte.
    """
    if not carnet:
        return 5.0, 0.0, "Pas encore d'historique"

    candidates = []
    for c in carnet:
        if c.get("espece") and c.get("espece") != species:
            continue
        if c.get("spot_id") and c.get("spot_id") != spot_id:
            continue

        cc = safe_float(c.get("coef"))
        if cc is not None and coef is not None and abs(cc - coef) > 15:
            continue

        candidates.append(c)

    if not candidates:
        return 5.0, 0.0, "Pas assez de sessions comparables"

    # Chaque session compte : prise = 1, bredouille = 0.
    outcomes = []
    for c in candidates:
        nb = safe_float(c.get("nb_poissons"), 0) or 0
        touches = safe_float(c.get("touches"), 0) or 0
        # Une touche sans prise est légèrement positive, sans devenir un succès.
        outcome = 1.0 if nb > 0 else (0.25 if touches > 0 else 0.0)
        outcomes.append(outcome)

    n = len(outcomes)
    # Lissage bayésien simple vers 0.5.
    posterior = (sum(outcomes) + 2.0 * 0.5) / (n + 2.0)
    score = 2.5 + 7.5 * posterior
    confidence = min(1.0, n / 10.0)

    return clamp(score), confidence, f"{n} session(s) comparable(s) — réussite lissée {posterior*100:.0f}%"


def infer_historical_reliability(carnet):
    if not carnet:
        return 0.0
    return min(1.0, len(carnet) / 20.0)


def score_confidence(days_ahead, data_flags, hist_conf, marine_available):
    # Prévision courte = plus fiable.
    forecast_conf = 1.0 if days_ahead <= 2 else (0.85 if days_ahead <= 4 else (0.70 if days_ahead <= 7 else 0.50))
    data_conf = sum(data_flags) / len(data_flags) if data_flags else 0.5
    marine_conf = 1.0 if marine_available else 0.35
    raw = 0.45 * forecast_conf + 0.30 * data_conf + 0.15 * marine_conf + 0.10 * hist_conf
    return int(round(max(25, min(95, raw * 100))))


def recommendation_for(species, technique, score, row, spot):
    if species == "Bar":
        if technique == "Surface":
            lure = "Surface 10–20 g, zones calmes/rochers ; privilégier aube ou crépuscule."
        elif technique == "Métal":
            lure = "Casting jig 20–40 g si vent/courant et poissons fourrage présents."
        elif technique == "Jerkbait / minnow":
            lure = "Minnow 12–18 cm, récupération lente à modérée près des cassures."
        else:
            lure = "Leurre souple 20–30 g ; tête plombée adaptée au courant, lancer en travers puis suivre la dérive."
        return lure
    else:
        if technique == "Crabe au posé":
            return "Crabe vert, montage coulissant 50–80 g, fluoro 40–45/100, bas de ligne 1–1,5 m, hameçon fort n°1–2."
        if technique == "Couteau / coquillage":
            return "Couteau/coquillage sur montage coulissant, 50–80 g ; privilégier les bordures de courant et fonds coquilliers."
        if technique == "Ver":
            return "Ver marin sur montage coulissant léger à moyen ; intéressant lorsque le courant est modéré."
        return "Surfcasting léger : 60–90 g selon courant, bas de ligne 40–45/100, appât naturel."


def choose_best_window(df, species, technique, spot, tides_dict, carnet):
    """Calcule un score par heure pour les prochaines 8 journées.
    On conserve les créneaux réellement disponibles dans les données."""
    rows = []

    if df.empty:
        return pd.DataFrame()

    local_df = df.copy()
    local_df["date_only"] = local_df["time"].dt.date
    today = datetime.now().date()

    for _, r in local_df.iterrows():
        dt = r["time"]
        if dt.date() < today:
            continue

        date_key = dt.strftime("%Y-%m-%d")
        tide_info = tides_dict.get(date_key, {})
        extrema = tide_info.get("extrema", [])
        coef = safe_float(tide_info.get("max_coef"), 70)

        phase_s, phase_desc, phase, _ = tide_phase_score(dt, extrema, species)
        coef_s = continuous_coef_score(coef, species)

        wind_s, wind_desc = wind_to_score(
            safe_float(r.get("wind_speed_10m")),
            safe_float(r.get("wind_direction_10m")),
            species,
        )
        wave_s, wave_desc = wave_score(
            safe_float(r.get("wave_height")),
            safe_float(r.get("wave_period")),
            species,
            spot,
        )
        pressure_s, pressure_desc = pressure_score(
            safe_float(r.get("surface_pressure")),
            safe_float(r.get("pressure_delta_3h")),
            safe_float(r.get("pressure_delta_6h")),
            safe_float(r.get("pressure_delta_12h")),
        )
        water_s, water_desc = water_score(
            safe_float(r.get("sea_surface_temperature")),
            safe_float(r.get("sst_delta_24h")),
            species,
        )
        light_s, light_desc = light_score(
            dt,
            safe_float(r.get("cloud_cover")),
            species,
        )
        hist_s, hist_conf, hist_desc = historical_score(
            carnet, spot["id"], species, technique, coef, dt
        )

        current = safe_float(r.get("ocean_current_velocity"))
        if current is None:
            current_s = 5.0
            current_desc = "Courant modèle indisponible"
        else:
            # km/h -> m/s ; pour la pêche, on cherche une plage exploitable,
            # pas le maximum absolu.
            cms = current / 3.6
            if species == "Daurade royale":
                if 0.15 <= cms <= 0.65:
                    current_s = 9.0
                elif 0.08 <= cms < 0.15 or 0.65 < cms <= 0.9:
                    current_s = 7.0
                elif cms < 0.08:
                    current_s = 5.0
                else:
                    current_s = 3.0
            else:
                if 0.12 <= cms <= 0.60:
                    current_s = 9.0
                elif 0.05 <= cms < 0.12 or 0.60 < cms <= 0.85:
                    current_s = 7.0
                elif cms < 0.05:
                    current_s = 5.0
                else:
                    current_s = 3.0
            current_desc = f"{cms:.2f} m/s"

        w = SPECIES[species]["weights"]
        score = (
            phase_s * w["maree"]
            + coef_s * 0.06
            + current_s * w["courant"]
            + wind_s * w["vent"]
            + wave_s * w["houle"]
            + light_s * w["lumiere"]
            + water_s * w["eau"]
            + pressure_s * w["pression"]
            + hist_s * w["historique"]
            + spot[species.lower().replace(" ", "_")] / 10 * w["spot"] * 10
        )

        # Le coefficient est déjà implicitement lié à la phase, mais on le
        # garde comme petit facteur distinct. Normalisation des poids :
        # la somme vaut > 1 dans la configuration ; on redivise.
        total_weight = (
            w["maree"] + 0.06 + w["courant"] + w["vent"] + w["houle"]
            + w["lumiere"] + w["eau"] + w["pression"] + w["historique"] + w["spot"]
        )
        score = score / total_weight * 10
        score = clamp(score, 0, 10) * 10

        flags = [
            safe_float(r.get("wind_speed_10m")) is not None,
            safe_float(r.get("surface_pressure")) is not None,
            safe_float(r.get("sea_surface_temperature")) is not None,
            bool(extrema),
            safe_float(r.get("wave_height")) is not None,
        ]
        confidence = score_confidence(
            max(0, (dt.date() - today).days),
            flags,
            hist_conf,
            safe_float(r.get("ocean_current_velocity")) is not None,
        )

        rows.append({
            "datetime": dt,
            "date": date_key,
            "heure": dt.strftime("%H:%M"),
            "score": round(score, 1),
            "confiance": confidence,
            "phase": phase,
            "coef": coef,
            "courant": current_desc,
            "vent": wind_desc,
            "houle": wave_desc,
            "pression": pressure_desc,
            "eau": water_desc,
            "lumiere": light_desc,
            "historique": hist_desc,
            "phase_desc": phase_desc,
            "wind_score": round(wind_s, 1),
            "current_score": round(current_s, 1),
            "wave_score": round(wave_s, 1),
            "pressure_score": round(pressure_s, 1),
            "water_score": round(water_s, 1),
            "light_score": round(light_s, 1),
            "tide_score": round(phase_s, 1),
            "coef_score": round(coef_s, 1),
        })

    return pd.DataFrame(rows)


# -----------------------------
# Persistance carnet
# -----------------------------
def charger_carnet():
    if not os.path.exists(CARNET_FILE):
        return []
    try:
        with open(CARNET_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def sauvegarder_carnet(carnet):
    with open(CARNET_FILE, "w", encoding="utf-8") as f:
        json.dump(carnet, f, ensure_ascii=False, indent=2)


# -----------------------------
# API
# -----------------------------
@st.cache_data(ttl=3600)
def fetch_weather(lat, lon):
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&hourly=temperature_2m,surface_pressure,wind_speed_10m,"
        "wind_direction_10m,cloud_cover,precipitation"
        "&forecast_days=16&past_hours=24&timezone=auto"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
        df = pd.DataFrame(data["hourly"])
        df["time"] = pd.to_datetime(df["time"])
        for c in df.columns:
            if c != "time":
                df[c] = pd.to_numeric(df[c], errors="coerce")
        return df
    except Exception as e:
        st.warning(f"Météo indisponible : {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def fetch_marine(lat, lon):
    # Open-Meteo Marine : jusqu'à 8 jours de prévision sur cet endpoint.
    variables = (
        "wave_height,wave_direction,wave_period,"
        "sea_surface_temperature,ocean_current_velocity,ocean_current_direction"
    )
    url = (
        "https://marine-api.open-meteo.com/v1/marine"
        f"?latitude={lat}&longitude={lon}"
        f"&hourly={variables}&forecast_days=8&past_hours=24"
        "&timezone=auto&cell_selection=sea"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
        df = pd.DataFrame(data["hourly"])
        df["time"] = pd.to_datetime(df["time"])
        for c in df.columns:
            if c != "time":
                df[c] = pd.to_numeric(df[c], errors="coerce")
        return df
    except Exception as e:
        st.warning(f"Données marines indisponibles : {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def fetch_tides(site_slug, start_date, end_date):
    if not API_KEY_MAREE:
        return {}

    url = (
        f"https://api-maree.fr/tide-extrema"
        f"?site={quote(str(site_slug))}"
        f"&from={start_date}&to={end_date}"
        f"&tz=Europe/Paris&key={quote(API_KEY_MAREE)}"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
        days = data if isinstance(data, list) else data.get("data", data.get("days", []))
        out = {}
        for day in days:
            d = day.get("date") or day.get("day")
            if not d:
                continue
            d = str(d).split("T")[0]
            extrema = day.get("extrema", [])
            coefs = [
                safe_float(e.get("coef"))
                for e in extrema
                if e.get("type") == "PM" and safe_float(e.get("coef")) is not None
            ]
            out[d] = {
                "max_coef": max(coefs) if coefs else 70,
                "extrema": extrema,
            }
        return out
    except Exception as e:
        st.warning(f"Marées indisponibles : {e}")
        return {}


# -----------------------------
# Interface
# -----------------------------
st.title("🎣 Indice de Pêche V5 — Bar & Daurade royale")
st.caption(
    "Le Croisic / Sud Bretagne · météo · marée · courant · houle · SST · historique personnel"
)

carnet = charger_carnet()

with st.sidebar:
    st.header("🎯 Ciblage")
    species = st.selectbox("Espèce", list(SPECIES.keys()))
    technique = st.selectbox("Technique", SPECIES[species]["techniques"])

    st.divider()
    st.header("📍 Spot")
    spot_names = [s["nom"] for s in SPOTS]
    selected_spot_name = st.selectbox("Secteur", spot_names)
    spot = next(s for s in SPOTS if s["nom"] == selected_spot_name)

    st.info(
        f"**{spot['fond']}**\n\n"
        f"Orientation : {spot['orientation']}°\n\n"
        f"{spot['notes']}"
    )

    st.divider()
    st.header("🗺️ Position météo")
    use_spot_coords = st.checkbox("Utiliser les coordonnées du spot", value=True)

# Coordonnées météo : par défaut le spot choisi.
lat_cible, lon_cible = spot["lat"], spot["lon"]

if not use_spot_coords:
    st.sidebar.write("Position personnalisée")
    lat_cible = st.sidebar.number_input(
        "Latitude", value=float(lat_cible), format="%.5f"
    )
    lon_cible = st.sidebar.number_input(
        "Longitude", value=float(lon_cible), format="%.5f"
    )

# -----------------------------
# Chargement données
# -----------------------------
with st.spinner("Chargement météo, mer et marées..."):
    df_weather = fetch_weather(lat_cible, lon_cible)
    df_marine = fetch_marine(lat_cible, lon_cible)

if df_weather.empty:
    st.error("Impossible de récupérer les données météo.")
    st.stop()

if not df_marine.empty:
    df = pd.merge_asof(
        df_weather.sort_values("time"),
        df_marine.sort_values("time"),
        on="time",
        direction="nearest",
        tolerance=pd.Timedelta("90min"),
    )
else:
    df = df_weather.copy()
    for c in [
        "wave_height", "wave_direction", "wave_period",
        "sea_surface_temperature", "ocean_current_velocity",
        "ocean_current_direction"
    ]:
        df[c] = float("nan")

# -----------------------------
# Variables dynamiques
# -----------------------------
for h in [3, 6, 12, 24]:
    df[f"pressure_delta_{h}h"] = (
        df["surface_pressure"] - df["surface_pressure"].shift(h)
    )

if "sea_surface_temperature" in df.columns:
    df["sst_delta_24h"] = (
        df["sea_surface_temperature"] - df["sea_surface_temperature"].shift(24)
    )

df["date"] = df["time"].dt.strftime("%Y-%m-%d")

# Marées
dates = sorted(df["date"].dropna().unique())
start_date = dates[0]
end_date = dates[-1]

# Fallback si pas de clé : on continue à afficher météo/mer.
tides_dict = fetch_tides(
    "le-croisic",
    start_date,
    end_date,
) if API_KEY_MAREE else {}

# Si api-maree n'est pas configurée, on signale clairement.
if not API_KEY_MAREE:
    st.warning(
        "⚠️ API_KEY_MAREE non configurée. Les scores marée/courant de marée "
        "seront partiels. Ajoute la clé dans les secrets Streamlit."
    )

# -----------------------------
# Score horaire
# -----------------------------
df_score = choose_best_window(
    df=df,
    species=species,
    technique=technique,
    spot=spot,
    tides_dict=tides_dict,
    carnet=carnet,
)

# -----------------------------
# En-tête synthèse
# -----------------------------
if not df_score.empty:
    best = df_score.sort_values(["score", "confiance"], ascending=False).iloc[0]

    st.success(
        f"{SPECIES[species]['emoji']} **Meilleur créneau détecté : "
        f"{best['datetime'].strftime('%a %d/%m à %H:%M')} — "
        f"{best['score']:.0f}/100** · confiance {best['confiance']}%"
    )

    rec = recommendation_for(
        species, technique, best["score"], best, spot
    )

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Indice", f"{best['score']:.0f}/100")
    k2.metric("Confiance", f"{best['confiance']}%")
    k3.metric("Coefficient", f"{best['coef']:.0f}")
    k4.metric("Phase", best["phase"])

    st.info(f"🎯 **Conseil :** {rec}")

# -----------------------------
# Tabs
# -----------------------------
tab_dashboard, tab_spots, tab_carnet, tab_stats, tab_sources = st.tabs(
    [
        "📊 Indice & créneaux",
        "🗺️ Carte des 10 spots",
        "📖 Carnet de sessions",
        "🧠 Analyse personnelle",
        "ℹ️ Données & limites",
    ]
)

# ============================================================
# TAB 1 : dashboard
# ============================================================
with tab_dashboard:
    if df_score.empty:
        st.warning("Pas assez de données pour calculer les créneaux.")
    else:
        st.subheader(
            f"{SPECIES[species]['emoji']} {species} — {technique} — {spot['nom']}"
        )

        # Top créneaux
        top = (
            df_score.sort_values(["score", "confiance"], ascending=False)
            .head(15)
            .copy()
        )
        top["Créneau"] = top["datetime"].dt.strftime("%d/%m %H:%M")
        top_display = top[
            [
                "Créneau", "score", "confiance", "phase", "coef",
                "courant", "vent", "houle", "pression", "eau"
            ]
        ].rename(
            columns={
                "score": "Indice",
                "confiance": "Confiance %",
                "phase": "Marée",
                "coef": "Coef",
                "courant": "Courant",
                "vent": "Vent",
                "houle": "Houle",
                "pression": "Pression",
                "eau": "Eau",
            }
        )

        st.markdown("### 🏆 Meilleurs créneaux")
        st.dataframe(
            top_display,
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("### 📅 Vue par jour")
        daily = (
            df_score.groupby("date")
            .agg(
                indice_max=("score", "max"),
                confiance=("confiance", "mean"),
                meilleur_heure=("heure", lambda x: x.iloc[0]),
            )
            .reset_index()
        )
        daily["date"] = pd.to_datetime(daily["date"]).dt.strftime("%d/%m")
        st.dataframe(
            daily.sort_values("indice_max", ascending=False),
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("### 🔍 Analyse détaillée")
        chosen_date = st.selectbox(
            "Date",
            sorted(df_score["date"].unique()),
            key="detail_date",
        )
        day = df_score[df_score["date"] == chosen_date].copy()

        if not day.empty:
            best_day = day.sort_values("score", ascending=False).iloc[0]
            st.markdown(
                f"#### {chosen_date} · meilleur moment {best_day['heure']} "
                f"→ **{best_day['score']:.0f}/100**"
            )

            a, b, c, d = st.columns(4)
            a.metric("Marée", f"{best_day['tide_score']:.1f}/10")
            b.metric("Courant", f"{best_day['current_score']:.1f}/10")
            c.metric("Houle", f"{best_day['wave_score']:.1f}/10")
            d.metric("Pression", f"{best_day['pressure_score']:.1f}/10")

            a, b, c, d = st.columns(4)
            a.metric("Eau", f"{best_day['water_score']:.1f}/10")
            b.metric("Lumière", f"{best_day['light_score']:.1f}/10")
            b.write(best_day["lumiere"] if "lumiere" in best_day else "")
            c.metric("Coefficient", f"{best_day['coef']:.0f}")
            d.metric("Confiance", f"{best_day['confiance']}%")

            st.write("**Pourquoi ce créneau ?**")
            reasons = [
                f"🌊 Marée : {best_day['phase_desc']}",
                f"🌊 Courant : {best_day['courant']}",
                f"🌬️ Vent : {best_day['vent']}",
                f"🌊 Houle : {best_day['houle']}",
                f"📉 Pression : {best_day['pression']}",
                f"🌡️ Eau : {best_day['eau']}",
                f"☀️ Lumière : {best_day['lumiere']}",
                f"📖 Historique : {best_day['historique']}",
            ]
            for reason in reasons:
                st.write(reason)

# ============================================================
# TAB 2 : carte spots
# ============================================================
with tab_spots:
    st.subheader("🗺️ 10 secteurs de prospection autour du Croisic")
    st.caption(
        "Les points sont des repères de secteur, pas des postes garantis. "
        "Vérifie l'accès, les concessions, les réserves, la réglementation "
        "locale et les conditions de sécurité avant de pêcher."
    )

    m = folium.Map(
        location=[CENTER["lat"], CENTER["lon"]],
        zoom_start=11,
        control_scale=True,
    )

    folium.Marker(
        [CENTER["lat"], CENTER["lon"]],
        popup="Le Croisic — centre de référence",
        tooltip="Le Croisic",
        icon=folium.Icon(color="blue", icon="home"),
    ).add_to(m)

    # Cercle ~20 km
    folium.Circle(
        [CENTER["lat"], CENTER["lon"]],
        radius=20000,
        color="#3388ff",
        fill=False,
        tooltip="Rayon ~20 km",
    ).add_to(m)

    for s in SPOTS:
        val = s["bar"] if species == "Bar" else s["daurade"]
        color = "green" if val >= 9 else ("orange" if val >= 8 else "blue")

        popup = (
            f"<b>{s['nom']}</b><br>"
            f"Fond : {s['fond']}<br>"
            f"Orientation : {s['orientation']}°<br>"
            f"Indice spot {species} : {val}/10<br>"
            f"{s['notes']}<br>"
            f"<b>Bar :</b> {s['techniques_bar']}<br>"
            f"<b>Daurade :</b> {s['techniques_daurade']}"
        )

        folium.Marker(
            [s["lat"], s["lon"]],
            popup=folium.Popup(popup, max_width=350),
            tooltip=f"{s['nom']} — {val}/10",
            icon=folium.Icon(color=color, icon="map-marker"),
        ).add_to(m)

    st_folium(m, height=600, width="100%", key="spots_map")

    spot_df = pd.DataFrame(
        [
            {
                "Spot": s["nom"],
                "Fond": s["fond"],
                "Bar /10": s["bar"],
                "Daurade /10": s["daurade"],
                "Orientation": f"{s['orientation']}°",
                "GPS": f"{s['lat']:.5f}, {s['lon']:.5f}",
            }
            for s in SPOTS
        ]
    )
    st.dataframe(spot_df, use_container_width=True, hide_index=True)

# ============================================================
# TAB 3 : carnet de sessions
# ============================================================
with tab_carnet:
    st.subheader("📖 Carnet de sessions")
    st.caption(
        "Une bredouille est une donnée utile : elle permet au moteur d'apprendre "
        "qu'un créneau apparemment favorable n'a pas forcément produit de poisson."
    )

    with st.form("form_session"):
        c1, c2, c3 = st.columns(3)
        with c1:
            session_date = st.date_input("Date", value=date.today())
            session_species = st.selectbox(
                "Espèce ciblée",
                list(SPECIES.keys()),
                index=list(SPECIES.keys()).index(species),
            )
            session_spot = st.selectbox(
                "Spot",
                spot_names,
                index=spot_names.index(selected_spot_name),
            )

        with c2:
            start_time = st.time_input("Début")
            end_time = st.time_input("Fin")
            session_technique = st.text_input("Technique / leurre", technique)

        with c3:
            nb_poissons = st.number_input(
                "Poissons pris", min_value=0, max_value=100, value=0
            )
            touches = st.number_input(
                "Touches", min_value=0, max_value=200, value=0
            )
            decroches = st.number_input(
                "Décrochés", min_value=0, max_value=200, value=0
            )

        c4, c5, c6 = st.columns(3)
        with c4:
            taille_max = st.number_input(
                "Taille max (cm)", min_value=0.0, max_value=150.0, value=0.0
            )
        with c5:
            poids_max = st.number_input(
                "Poids max (kg)", min_value=0.0, max_value=30.0, value=0.0
            )
        with c6:
            coef_session = st.number_input(
                "Coefficient", min_value=0, max_value=120, value=70
            )

        comment = st.text_area(
            "Observations",
            placeholder="Poste, fond, appât/leurre, animation, courant, comportement des poissons..."
        )

        submit = st.form_submit_button("💾 Enregistrer la session")

        if submit:
            chosen = next(s for s in SPOTS if s["nom"] == session_spot)

            entry = {
                "date": session_date.strftime("%Y-%m-%d"),
                "heure_debut": start_time.strftime("%H:%M"),
                "heure_fin": end_time.strftime("%H:%M"),
                "espece": session_species,
                "spot_id": chosen["id"],
                "spot": chosen["nom"],
                "lat": chosen["lat"],
                "lon": chosen["lon"],
                "technique": session_technique,
                "nb_poissons": int(nb_poissons),
                "touches": int(touches),
                "decroches": int(decroches),
                "taille_max_cm": float(taille_max),
                "poids_max_kg": float(poids_max),
                "coef": int(coef_session),
                "commentaire": comment,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }

            carnet.append(entry)
            sauvegarder_carnet(carnet)
            st.success("✅ Session enregistrée.")
            st.rerun()

    st.divider()

    if carnet:
        df_c = pd.DataFrame(carnet)
        st.dataframe(df_c, use_container_width=True, hide_index=True)

        b1, b2 = st.columns(2)
        with b1:
            if st.button("🗑️ Vider le carnet"):
                try:
                    os.remove(CARNET_FILE)
                except FileNotFoundError:
                    pass
                st.rerun()
        with b2:
            st.download_button(
                "⬇️ Télécharger le carnet JSON",
                data=json.dumps(carnet, ensure_ascii=False, indent=2),
                file_name="carnet_peche_v5.json",
                mime="application/json",
            )
    else:
        st.info("Aucune session enregistrée.")

# ============================================================
# TAB 4 : statistiques personnelles
# ============================================================
with tab_stats:
    st.subheader("🧠 Analyse personnelle")

    if not carnet:
        st.warning("Enregistre au moins quelques sessions pour commencer l'apprentissage.")
    else:
        df_c = pd.DataFrame(carnet)

        # Normalisation des colonnes anciennes éventuelles.
        if "espece" not in df_c:
            df_c["espece"] = "Bar"
        if "nb_poissons" not in df_c:
            df_c["nb_poissons"] = 0
        if "coef" not in df_c:
            df_c["coef"] = 70

        total_sessions = len(df_c)
        successful = int((pd.to_numeric(df_c["nb_poissons"], errors="coerce").fillna(0) > 0).sum())
        success_rate = successful / total_sessions * 100 if total_sessions else 0

        m1, m2, m3 = st.columns(3)
        m1.metric("Sessions", total_sessions)
        m2.metric("Sessions avec poisson", successful)
        m3.metric("Taux de réussite", f"{success_rate:.0f}%")

        st.markdown("### 🐟 Résultats par espèce")
        grp = (
            df_c.assign(
                prise=pd.to_numeric(df_c["nb_poissons"], errors="coerce").fillna(0) > 0
            )
            .groupby("espece")
            .agg(
                sessions=("prise", "size"),
                sessions_avec_poisson=("prise", "sum"),
                poissons=("nb_poissons", "sum"),
                coef_moyen=("coef", "mean"),
            )
            .reset_index()
        )
        grp["taux_reussite_%"] = (
            grp["sessions_avec_poisson"] / grp["sessions"] * 100
        ).round(1)
        st.dataframe(grp, use_container_width=True, hide_index=True)

        st.markdown("### 🗺️ Tes spots les plus rentables")
        spot_grp = (
            df_c.assign(
                prise=pd.to_numeric(df_c["nb_poissons"], errors="coerce").fillna(0) > 0
            )
            .groupby(["spot", "espece"])
            .agg(
                sessions=("prise", "size"),
                poissons=("nb_poissons", "sum"),
                taux_reussite=("prise", "mean"),
            )
            .reset_index()
        )
        spot_grp["taux_reussite"] = (spot_grp["taux_reussite"] * 100).round(1)
        st.dataframe(
            spot_grp.sort_values(
                ["taux_reussite", "poissons"], ascending=False
            ),
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("### 🌊 Coefficients observés")
        coef_grp = (
            df_c.assign(
                prise=pd.to_numeric(df_c["nb_poissons"], errors="coerce").fillna(0) > 0,
                coef_num=pd.to_numeric(df_c["coef"], errors="coerce"),
            )
            .dropna(subset=["coef_num"])
            .groupby(pd.cut(
                df_c.assign(coef_num=pd.to_numeric(df_c["coef"], errors="coerce"))["coef_num"],
                bins=[0, 45, 60, 75, 90, 105, 120],
                include_lowest=True,
            ))
            .agg(
                sessions=("prise", "size"),
                sessions_avec_poisson=("prise", "sum"),
            )
            .reset_index()
        )
        if not coef_grp.empty:
            coef_grp["taux_reussite_%"] = (
                coef_grp["sessions_avec_poisson"]
                / coef_grp["sessions"] * 100
            ).round(1)
            st.dataframe(coef_grp, use_container_width=True, hide_index=True)

        st.info(
            "ℹ️ Le moteur V5 utilise actuellement un lissage statistique simple. "
            "Avec 20–50 sessions bien renseignées, on pourra passer à un modèle "
            "plus robuste (régression logistique / gradient boosting) sans "
            "changer le carnet de données."
        )

# ============================================================
# TAB 5 : sources / limites
# ============================================================
with tab_sources:
    st.subheader("ℹ️ Données utilisées et limites")

    st.markdown(
        """
### Données météo
- Open-Meteo : température, pression, vent, direction, nuages, précipitations.
- Prévision météo jusqu'à 16 jours.
- La confiance diminue automatiquement avec l'éloignement de la date.

### Données marines
- Open-Meteo Marine : hauteur/direction/période de houle, SST,
  vitesse et direction du courant.
- La disponibilité de la prévision marine est plus courte que la météo
  atmosphérique dans cette version.
- Le courant est un **courant modèle** : il doit être considéré comme
  un indicateur et non comme une mesure locale précise.

### Marées
- api-maree.fr si `API_KEY_MAREE` est configurée.
- Le score utilise la phase de marée et le coefficient au lieu d'un simple
  seuil binaire.

### Historique
- Les sessions avec et sans poisson sont conservées.
- Le moteur utilise un lissage simple pour éviter de surinterpréter une
  poignée de sorties.
"""
    )

    st.markdown("### ⚠️ Sécurité / réglementation")
    st.warning(
        "Les spots sont des repères de prospection. Ne pêche pas dans une zone "
        "interdite, sur une concession ostréicole, une réserve ou une zone "
        "réglementée. La houle et les rochers peuvent rendre certains secteurs "
        "dangereux, notamment autour des pointes et digues."
    )

    st.markdown("### 🔧 Configuration")
    if API_KEY_MAREE:
        st.success("API_KEY_MAREE détectée.")
    else:
        st.error("API_KEY_MAREE absente.")

# -----------------------------
# Footer
# -----------------------------
st.divider()
st.caption(
    "Indice Pêche V5 — outil d'aide à la décision. "
    "Un score élevé indique une combinaison de conditions plus proche "
    "des hypothèses du modèle ; il ne garantit pas une prise."
)