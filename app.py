import streamlit as st
import requests
import pandas as pd
import json
import os
from datetime import datetime, timedelta, date
import time
import math
import re
from io import BytesIO
import zipfile
from urllib.parse import quote
from streamlit_folium import st_folium
import folium
try:
    import xarray as xr
except Exception:
    xr = None

import db_supabase as db

# ============================================================
# AIDE À LA DÉCISION PÊCHE V6.2
# Bar & Daurade royale - Le Croisic / Sud Bretagne
#
# V6.2 :
# - profils espèce + technique
# - 10 spots préconfigurés autour du Croisic (~20 km)
# - météo 14 j, point de référence fixe par défaut
# - météo marine : houle, direction, période, SST, courant
# - marées api-maree.fr
# - phase de marée continue
# - pression dynamique
# - température eau + évolution
# - score spécifique au spot / espèce / technique
# - score de confiance
# - recommandation automatique du meilleur créneau
# - carnet de SESSIONS + CAPTURES détaillées : succès et bredouilles
# - statistiques personnelles
# - stockage persistant Supabase (Postgres + Storage + Auth + RLS),
#   indépendant du disque local Streamlit
# - cache partagé Supabase pour les données SHOM et météo/marine
#   prétraitées, pour éviter de retraiter/rappeler les API à chaque
#   lancement
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
    page_title="Indice Pêche V6.2 — Bar & Daurade",
    page_icon="🎣",
    layout="wide",
)

# Zone de référence utilisée comme clé de cache partagé (SHOM / météo).
ZONE = "le_croisic"

# L'appli s'arrête ici tant que l'utilisateur n'est pas connecté à Supabase.
if not db.require_login_ui():
    st.stop()

# -----------------------------
# Configuration
# -----------------------------
HEADERS = {"User-Agent": "IndicePecheV6/1.0"}

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



# -----------------------------
# Courants SHOM 2D
# -----------------------------
def _find_coord_name(ds, candidates):
    names = list(ds.coords) + list(ds.dims)
    for c in candidates:
        for n in names:
            if n.lower() == c.lower():
                return n
    for n in names:
        low = n.lower()
        if any(c.lower() in low for c in candidates):
            return n
    return None


def _find_var_name(ds, candidates):
    for c in candidates:
        for n in ds.data_vars:
            if n.lower() == c.lower():
                return n
    for n in ds.data_vars:
        low = n.lower()
        if any(c.lower() in low for c in candidates):
            return n
    return None


def _read_shom_txt_bytes(raw, filename="courants.txt"):
    """Lecture tolérante des TXT SHOM Courants 2D.

    Le produit officiel actuellement publié par le SHOM est en TXT ASCII/WGS84.
    Les fichiers contiennent des points de courant et des échéances relatives à
    PM/BM. Comme les vues peuvent avoir des structures de colonnes différentes,
    on privilégie les noms de colonnes lorsqu'ils sont présents et on refuse de
    deviner silencieusement une structure ambiguë.
    """
    # Détection encodage simple
    txt = raw.decode("utf-8", errors="replace")
    lines = txt.splitlines()
    nonempty = [x.strip() for x in lines if x.strip() and not x.lstrip().startswith("#")]
    if not nonempty:
        raise ValueError("Fichier TXT vide.")

    # Plusieurs séparateurs possibles dans les exports ASCII SHOM.
    candidates = [r"\\s+", r"[;\\t]+", r"[,;\\t]+"]
    best = None
    for sep in candidates:
        try:
            df = pd.read_csv(BytesIO(raw), sep=sep, engine="python", comment="#")
            if df.shape[1] >= 4:
                best = df
                break
        except Exception:
            pass

    if best is None:
        # Dernier essai sans en-tête : on ne garde que les lignes numériques.
        rows = []
        for line in nonempty:
            parts = re.split(r"[;\\s,]+", line)
            nums = []
            for x in parts:
                try:
                    nums.append(float(x.replace(',', '.')))
                except Exception:
                    pass
            if len(nums) >= 4:
                rows.append(nums)
        if not rows:
            raise ValueError("Aucune ligne numérique exploitable trouvée dans le TXT SHOM.")
        width = max(len(r) for r in rows)
        best = pd.DataFrame([r + [float('nan')] * (width-len(r)) for r in rows])

    best.columns = [str(c).strip().lower() for c in best.columns]
    return best


def _normalise_shom_columns(df):
    """Normalise un tableau SHOM vers lat/lon/u/v/offset_h/coefficient."""
    cols = list(df.columns)
    def pick(words):
        for w in words:
            for c in cols:
                if w == c or w in c:
                    return c
        return None

    lat = pick(["latitude", "lat", "y"])
    lon = pick(["longitude", "lon", "long", "x"])
    u = pick(["u", "courant_u", "eastward", "est"])
    v = pick(["v", "courant_v", "northward", "nord"])
    offset = pick(["offset_h", "delta_h", "heure", "hour", "time_h", "echeance"])
    coeff = pick(["coefficient", "coeff", "coef"])
    phase = pick(["phase", "reference", "pm_bm", "type"])

    # Les exports peuvent ne pas nommer U/V. On ne fait pas de déduction
    # silencieuse à partir de colonnes numériques : mieux vaut demander un
    # format identifiable que calculer un courant faux.
    if not all([lat, lon, u, v]):
        raise ValueError(
            "Colonnes SHOM non reconnues. Le fichier doit permettre d'identifier "
            "latitude, longitude, U et V. Ouvre le TXT et vérifie son en-tête."
        )

    out = pd.DataFrame({
        "lat": pd.to_numeric(df[lat], errors="coerce"),
        "lon": pd.to_numeric(df[lon], errors="coerce"),
        "u": pd.to_numeric(df[u], errors="coerce"),
        "v": pd.to_numeric(df[v], errors="coerce"),
    })
    out["offset_h"] = pd.to_numeric(df[offset], errors="coerce") if offset else float("nan")
    out["coefficient"] = pd.to_numeric(df[coeff], errors="coerce") if coeff else float("nan")
    out["phase"] = df[phase].astype(str) if phase else ""
    out = out.dropna(subset=["lat", "lon", "u", "v"]).copy()
    return out


def load_shom_dataset(uploaded_file):
    """Charge soit le NetCDF 2D, soit le TXT/ZIP du produit SHOM."""
    if uploaded_file is None:
        return None, None
    raw = uploaded_file.getvalue()
    name = uploaded_file.name.lower()

    # NetCDF (produit/variante documenté par le SHOM)
    if name.endswith((".nc", ".nc4", ".netcdf")):
        if xr is None:
            return None, "xarray/netCDF4 n'est pas installé."
        try:
            return {"kind": "netcdf", "data": xr.open_dataset(BytesIO(raw))}, None
        except Exception as e:
            return None, str(e)

    # ZIP : le produit de téléchargement peut contenir plusieurs TXT de vues.
    if name.endswith(".zip"):
        try:
            z = zipfile.ZipFile(BytesIO(raw))
            frames = []
            for info in z.infolist():
                if info.is_dir() or not info.filename.lower().endswith(".txt"):
                    continue
                try:
                    d = _normalise_shom_columns(_read_shom_txt_bytes(z.read(info), info.filename))
                    d["source_file"] = info.filename
                    frames.append(d)
                except Exception:
                    continue
            if not frames:
                raise ValueError("Aucun TXT SHOM exploitable trouvé dans le ZIP.")
            return {"kind": "txt", "data": pd.concat(frames, ignore_index=True)}, None
        except Exception as e:
            return None, str(e)

    if name.endswith(".txt"):
        try:
            df = _normalise_shom_columns(_read_shom_txt_bytes(raw, name))
            return {"kind": "txt", "data": df}, None
        except Exception as e:
            return None, str(e)

    return None, "Format SHOM attendu : .txt, .zip ou .nc/.nc4."


def shom_current_at(ds, lat, lon, dt, tide_info, reference="PM"):
    if ds is None:
        return None
    if isinstance(ds, dict) and ds.get("kind") == "txt":
        return shom_current_txt(ds["data"], lat, lon, dt, tide_info, reference)
    if isinstance(ds, dict) and ds.get("kind") == "netcdf":
        ds = ds["data"]
    """Retourne le courant SHOM au spot/heure.

    Le SHOM fournit directement U/V pour les coefficients 45 et 95 et les
    échéances relatives à la PM/BM. On n'effectue qu'une interpolation
    linéaire du coefficient entre 45 et 95, puis une interpolation spatiale
    dans la grille. Aucune modélisation du courant n'est créée ici.
    """
    if ds is None:
        return None

    lat_name = _find_coord_name(ds, ["latitude", "lat", "y"])
    lon_name = _find_coord_name(ds, ["longitude", "lon", "x"])
    time_name = _find_coord_name(ds, ["time", "echeance", "t"])
    coeff_name = _find_coord_name(ds, ["coeff", "coefficient", "coef"])
    u_name = _find_var_name(ds, ["u", "eastward_velocity", "current_u", "voz"])
    v_name = _find_var_name(ds, ["v", "northward_velocity", "current_v", "von"])

    if not all([lat_name, lon_name, time_name, coeff_name, u_name, v_name]):
        return None

    extrema = tide_info.get("extrema", []) if tide_info else []
    if not extrema:
        return None

    # Choix de l'événement de référence (PM ou BM), puis calcul de l'échéance.
    candidates = []
    for e in extrema:
        try:
            et = pd.Timestamp(e["datetime"])
            typ = str(e.get("type", "")).upper()
            if reference == "PM" and "PM" not in typ:
                continue
            if reference == "BM" and "BM" not in typ:
                continue
            delta_h = (pd.Timestamp(dt) - et).total_seconds() / 3600.0
            if -6.01 <= delta_h <= 6.01:
                candidates.append((abs(delta_h), delta_h, et))
        except Exception:
            continue

    if not candidates:
        return None
    _, delta_h, _ = min(candidates)

    # Le SHOM documente des pas de 1h/30min/5min selon la grille.
    try:
        time_values = ds[time_name].values
        # Le produit SHOM référence PM à 12:00 fictive, avec une origine
        # 1950-01-01 06:00Z. Pour une coordonnée numérique, l'échéance
        # vaut donc 720 minutes + delta_h*60.
        if getattr(time_values, "dtype", None) is not None and str(time_values.dtype).startswith("datetime64"):
            time_sel = pd.Timestamp("1950-01-01T12:00:00") + pd.to_timedelta(delta_h, unit="h")
        else:
            time_sel = 720.0 + delta_h * 60.0
    except Exception:
        return None

    # Coefficient : interpolation linéaire 45 -> 95, sans extrapolation.
    coef = safe_float(tide_info.get("max_coef"), 70)
    coef_used = max(45.0, min(95.0, float(coef)))
    try:
        ds45 = ds.sel({coeff_name: 45}, method="nearest")
        ds95 = ds.sel({coeff_name: 95}, method="nearest")
        # Sélection temporelle puis spatiale.
        def sample(d):
            q = d
            try:
                q = q.sel({time_name: time_sel}, method="nearest")
            except Exception:
                # Cas où time est déjà une simple échéance numérique.
                vals = q[time_name].values
                idx = int(min(range(len(vals)), key=lambda i: abs(float(vals[i]) - delta_h)))
                q = q.isel({time_name: idx})
            # Le produit est surface ; si une dimension profondeur est
            # présente, on prend la couche la plus proche de 0 m.
            depth_name = _find_coord_name(q.to_dataset(name="_q"), ["depth", "profondeur", "z"])
            if depth_name is not None and depth_name in q.dims:
                try:
                    q = q.sel({depth_name: 0}, method="nearest")
                except Exception:
                    q = q.isel({depth_name: 0})
            try:
                q = q.interp({lat_name: lat, lon_name: lon}, method="linear")
            except Exception:
                q = q.sel({lat_name: lat, lon_name: lon}, method="nearest")
            return float(q.values.squeeze())

        u45 = sample(ds45[u_name])
        v45 = sample(ds45[v_name])
        u95 = sample(ds95[u_name])
        v95 = sample(ds95[v_name])
        alpha = (coef_used - 45.0) / 50.0
        u = u45 + alpha * (u95 - u45)
        v = v45 + alpha * (v95 - v45)
        speed = math.hypot(u, v)
        # Direction vers laquelle porte le courant.
        direction = (math.degrees(math.atan2(u, v)) + 360) % 360
        return {
            "u": u,
            "v": v,
            "speed_ms": speed,
            "speed_kn": speed * 1.943844,
            "direction": direction,
            "coef": coef,
            "coef_used": coef_used,
            "delta_h": delta_h,
            "reference": reference,
        }
    except Exception:
        return None



def shom_current_txt(df, lat, lon, dt, tide_info, reference="PM"):
    """Courant SHOM TXT : interpolation spatiale minimale + coefficient 45/95.

    Le produit donne les valeurs U/V aux échéances du cycle. Nous n'inventons
    pas de courant : nous sélectionnons le point SHOM le plus proche et
    interpolons uniquement entre les situations 45 et 95 quand elles sont
    présentes. La conversion U/V -> vitesse/direction est purement géométrique.
    """
    if df is None or df.empty:
        return None
    extrema = tide_info.get("extrema", []) if tide_info else []
    candidates=[]
    for e in extrema:
        try:
            et=pd.Timestamp(e["datetime"]); typ=str(e.get("type","")).upper()
            if reference == "PM" and "PM" not in typ: continue
            if reference == "BM" and "BM" not in typ: continue
            dh=(pd.Timestamp(dt)-et).total_seconds()/3600
            if -6.01 <= dh <= 6.01: candidates.append((abs(dh),dh))
        except Exception: pass
    if not candidates: return None
    _, dh=min(candidates)

    d=df.copy()
    # Certains exports ont le coefficient sous forme ME/VE plutôt que 45/95.
    coef=safe_float(tide_info.get("max_coef"),70)
    target=max(45.0,min(95.0,float(coef)))
    if d["coefficient"].notna().any():
        d45=d[d["coefficient"].sub(45).abs()<1e-6]
        d95=d[d["coefficient"].sub(95).abs()<1e-6]
        if d45.empty or d95.empty:
            # Si une seule situation est fournie, ne pas extrapoler.
            return None
        def nearest(frame):
            frame=frame.copy()
            frame["dist"]=(frame["lat"]-lat)**2 + ((frame["lon"]-lon)*math.cos(math.radians(lat)))**2
            # L'échéance est normalement en heures relatives à PM/BM.
            if frame["offset_h"].notna().any(): frame["dist"] += (frame["offset_h"]-dh).fillna(99)**2
            return frame.sort_values("dist").iloc[0]
        a=nearest(d45); b=nearest(d95)
        alpha=(target-45)/50
        u=float(a.u)+alpha*(float(b.u)-float(a.u)); v=float(a.v)+alpha*(float(b.v)-float(a.v))
    else:
        # Pas de coefficient explicite : impossible de faire l'interpolation 45/95
        return None
    speed=math.hypot(u,v)
    direction=(math.degrees(math.atan2(u,v))+360)%360
    return {"u":u,"v":v,"speed_ms":speed,"speed_kn":speed*1.943844,
            "direction":direction,"coef":coef,"coef_used":target,
            "delta_h":dh,"reference":reference}

def current_score_value(speed_ms, species):
    if speed_ms is None:
        return 5.0
    if species == "Daurade royale":
        if 0.15 <= speed_ms <= 0.65:
            return 9.0
        if 0.08 <= speed_ms < 0.15 or 0.65 < speed_ms <= 0.90:
            return 7.0
        if speed_ms < 0.08:
            return 5.0
        return 3.0
    if 0.12 <= speed_ms <= 0.60:
        return 9.0
    if 0.05 <= speed_ms < 0.12 or 0.60 < speed_ms <= 0.85:
        return 7.0
    if speed_ms < 0.05:
        return 5.0
    return 3.0


def choose_best_window(df, species, technique, spot, tides_dict, carnet, shom_ds=None, shom_reference="PM"):
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

        shom_current = shom_current_at(
            shom_ds, spot["lat"], spot["lon"], dt, tide_info, reference=shom_reference
        )
        if shom_current is not None:
            current_s = current_score_value(shom_current["speed_ms"], species)
            current_desc = (
                f"SHOM {shom_current['speed_kn']:.2f} nd → {shom_current['direction']:.0f}°"
            )
            current_available = True
        else:
            current = safe_float(r.get("ocean_current_velocity"))
            if current is None:
                current_s = 5.0
                current_desc = "Courant indisponible"
                current_available = False
            else:
                cms = current / 3.6
                current_s = current_score_value(cms, species)
                current_desc = f"Modèle {cms:.2f} m/s"
                current_available = False

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
            current_available,
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
# Persistance carnet (Supabase)
# -----------------------------
def _carnet_from_sessions(sessions):
    """Adapte les lignes `sessions` Supabase au format attendu par
    historical_score()/choose_best_window() (espece, spot_id, coef,
    nb_poissons, touches), sans toucher à ces fonctions.
    """
    out = []
    for s in sessions:
        cond = s.get("conditions") or {}
        maree = cond.get("maree") or {}
        out.append({
            "espece": s.get("espece_ciblee"),
            "spot_id": s.get("spot_id"),
            "coef": maree.get("coefficient"),
            "nb_poissons": s.get("nb_poissons", 0),
            "touches": s.get("touches", 0),
        })
    return out


# -----------------------------
# API
# -----------------------------
def _open_meteo_get(url, label="Open-Meteo"):
    """GET robuste : retries sur 429/5xx et attente progressive."""
    last_error = None
    for attempt in range(4):
        try:
            r = requests.get(
                url,
                headers={**HEADERS, "Accept": "application/json", "Connection": "close"},
                timeout=20,
            )
            if r.status_code == 429:
                retry_after = r.headers.get("Retry-After")
                try:
                    wait = min(20, max(2, int(float(retry_after)))) if retry_after else 3 * (attempt + 1)
                except Exception:
                    wait = 3 * (attempt + 1)
                last_error = RuntimeError(f"{label}: HTTP 429 — limite de requêtes atteinte")
                if attempt < 3:
                    time.sleep(wait)
                    continue
                raise last_error

            if r.status_code >= 500:
                last_error = RuntimeError(f"{label}: serveur HTTP {r.status_code}")
                if attempt < 3:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise last_error

            r.raise_for_status()
            return r.json()

        except (requests.RequestException, RuntimeError) as e:
            last_error = e
            if attempt < 3:
                time.sleep(1.5 * (attempt + 1))
            else:
                raise last_error

    raise last_error or RuntimeError(f"{label}: erreur inconnue")


def _hourly_to_df(data):
    hourly = data.get("hourly", {})
    if not hourly or "time" not in hourly:
        raise ValueError("Réponse Open-Meteo sans données horaires.")
    df = pd.DataFrame(hourly)
    df["time"] = pd.to_datetime(df["time"])
    for c in df.columns:
        if c != "time":
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


@st.cache_data(ttl=21600, max_entries=12, show_spinner=False)
def fetch_weather(lat, lon):
    lat = round(float(lat), 2)
    lon = round(float(lon), 2)
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&hourly=temperature_2m,surface_pressure,wind_speed_10m,"
        "wind_direction_10m,cloud_cover,precipitation"
        "&forecast_days=14&timezone=Europe%2FParis"
    )
    try:
        return _hourly_to_df(_open_meteo_get(url, "Météo Open-Meteo"))
    except Exception as e:
        st.warning(f"Météo indisponible après plusieurs tentatives : {e}")
        return pd.DataFrame()


@st.cache_data(ttl=21600, max_entries=12, show_spinner=False)
def fetch_marine(lat, lon):
    lat = round(float(lat), 2)
    lon = round(float(lon), 2)
    variables = (
        "wave_height,wave_direction,wave_period,"
        "sea_surface_temperature,ocean_current_velocity,ocean_current_direction"
    )
    url = (
        "https://marine-api.open-meteo.com/v1/marine"
        f"?latitude={lat}&longitude={lon}"
        f"&hourly={variables}&forecast_days=8"
        "&timezone=Europe%2FParis&cell_selection=sea"
    )
    try:
        return _hourly_to_df(_open_meteo_get(url, "Marine Open-Meteo"))
    except Exception as e:
        st.warning(f"Données marines indisponibles après plusieurs tentatives : {e}")
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
# Cache partagé Supabase (météo / marine)
# Vient s'ajouter au @st.cache_data local (rapide, mais perdu à chaque
# redéploiement) : la donnée reste disponible même si le conteneur
# Streamlit redémarre, et est partagée entre tes différents appareils.
# -----------------------------
def _df_to_json_records(df):
    """Convertit un DataFrame en liste de dicts JSON-compatible :
    - colonne 'time' (Timestamp pandas) -> chaîne ISO
    - NaN -> None (le JSON strict de httpx refuse NaN/Infinity)
    """
    d = df.copy()
    if "time" in d.columns:
        d["time"] = d["time"].astype(str)
    return d.where(pd.notnull(d), None).to_dict(orient="records")


def _fetch_weather_cached(lat, lon, force=False):
    zone_key = f"{ZONE}_{round(float(lat), 2)}_{round(float(lon), 2)}"
    if not force:
        cached = db.get_cached_meteo(zone_key, "meteo")
        if cached is not None:
            df = pd.DataFrame(cached)
            if not df.empty and "time" in df.columns:
                df["time"] = pd.to_datetime(df["time"])
            return df
    df = fetch_weather(lat, lon)
    if not df.empty:
        db.store_meteo_cache(zone_key, "meteo", _df_to_json_records(df), ttl_seconds=21600)
    return df


def _fetch_marine_cached(lat, lon, force=False):
    zone_key = f"{ZONE}_{round(float(lat), 2)}_{round(float(lon), 2)}"
    if not force:
        cached = db.get_cached_meteo(zone_key, "marine")
        if cached is not None:
            df = pd.DataFrame(cached)
            if not df.empty and "time" in df.columns:
                df["time"] = pd.to_datetime(df["time"])
            return df
    df = fetch_marine(lat, lon)
    if not df.empty:
        db.store_meteo_cache(zone_key, "marine", _df_to_json_records(df), ttl_seconds=21600)
    return df


# -----------------------------
# Interface
# -----------------------------
st.title("🎣 Indice de Pêche V6.2 — Bar & Daurade royale")
st.caption(
    "Le Croisic / Sud Bretagne · météo · marée · courant · houle · SST · historique personnel"
)

# Une seule lecture Supabase pour la session Streamlit courante ; réutilisée
# pour le score, l'onglet Carnet et l'onglet Statistiques.
sessions_data = db.load_sessions()
captures_data = db.load_captures()
carnet = _carnet_from_sessions(sessions_data)

with st.sidebar:
    user = st.session_state.get("sb_user")
    if user:
        st.caption(f"Connecté : {user.email}")
        if st.button("🚪 Se déconnecter"):
            db.sign_out()
            st.rerun()
    st.divider()

    st.header("🎯 Ciblage")
    species = st.selectbox("Espèce", list(SPECIES.keys()))
    technique = st.selectbox("Technique", SPECIES[species]["techniques"])

    st.divider()
    st.header("📍 Zone de pêche")
    zone_mode = st.radio("Mode", ["🏠 Zone habituelle", "🧳 Déplacement / vacances"], index=0)

    if zone_mode == "🏠 Zone habituelle":
        spot_names = [s["nom"] for s in SPOTS]
        selected_spot_name = st.selectbox("Secteur", spot_names)
        spot = next(s for s in SPOTS if s["nom"] == selected_spot_name)
    else:
        zone_name = st.text_input("Nom de la zone", value="Nouveau secteur")
        vac_lat = st.number_input("Latitude", value=float(CENTER["lat"]), format="%.5f")
        vac_lon = st.number_input("Longitude", value=float(CENTER["lon"]), format="%.5f")
        spot = {
            "id": "custom_" + re.sub(r"[^a-z0-9]+", "_", zone_name.lower()).strip("_")[:40],
            "nom": zone_name, "lat": vac_lat, "lon": vac_lon,
            "fond": "À renseigner", "orientation": 0, "exposition": "À renseigner",
            "bar": 5, "daurade": 5,
            "notes": "Spot personnalisé : compléter les caractéristiques locales.",
            "techniques_bar": "À adapter", "techniques_daurade": "À adapter",
        }

    st.info(
        f"**{spot['fond']}**\n\n"
        f"Coordonnées : {spot['lat']:.5f}, {spot['lon']:.5f}\n\n"
        f"{spot['notes']}"
    )

    st.divider()
    st.header("🌊 Courants SHOM")
    shom_reference = st.selectbox(
        "Référence temporelle de l'atlas", ["PM", "BM"], index=0,
        help="Le produit SHOM encode les échéances autour de la PM ou BM du port de référence de la grille."
    )
    shom_file = st.file_uploader(
        "Importer le paquet SHOM Courants 2D (.zip/.txt/.nc)",
        type=["zip", "txt", "nc", "nc4"],
        help="Le produit officiel Courants 2D est diffusé gratuitement sous Licence Ouverte. Le produit actuellement publié est en TXT/WGS84 ; la variante NetCDF est aussi documentée par le SHOM."
    )

    st.info(
        f"**{spot['fond']}**\n\n"
        f"Orientation : {spot['orientation']}°\n\n"
        f"{spot['notes']}"
    )

    st.divider()
    st.header("🗺️ Position météo")
    use_spot_coords = st.checkbox(
    "Utiliser les coordonnées exactes du spot",
    value=False,
)

def _load_shom_with_shared_cache(uploaded_file, zone, reference):
    """Comme load_shom_dataset(), mais sert un cache partagé Supabase
    (table cache_shom) quand ce même paquet a déjà été traité par toi
    ou par une session précédente — évite de reparser le ZIP à chaque
    lancement.
    Le cache ne couvre que le format TXT/ZIP (sérialisable en JSON) ;
    le NetCDF continue d'être traité directement, sans mise en cache.
    """
    if uploaded_file is None:
        return None, None

    if uploaded_file.name.lower().endswith((".nc", ".nc4", ".netcdf")):
        return load_shom_dataset(uploaded_file)

    def _process(f):
        ds, err = load_shom_dataset(f)
        if err:
            raise RuntimeError(err)
        return {"kind": "txt", "records": _df_to_json_records(ds["data"])}

    try:
        cached = db.load_shom_dataset_cached(uploaded_file, zone, reference, _process)
    except Exception as e:
        return None, str(e)

    if cached is None:
        return None, None
    return {"kind": "txt", "data": pd.DataFrame(cached["records"])}, None


# Chargement du fichier SHOM (si fourni), via le cache partagé Supabase.
shom_ds, shom_error = _load_shom_with_shared_cache(shom_file, ZONE, shom_reference)
if shom_error:
    st.sidebar.error(f"Fichier SHOM illisible : {shom_error}")
elif shom_ds is not None:
    st.sidebar.success("✅ Courants SHOM chargés (cache partagé) : utilisés dans le score horaire")
else:
    st.sidebar.caption("Courants SHOM : importer le paquet TXT/ZIP (ou NetCDF si disponible) pour activer le calcul local.")

# Par défaut, une seule cellule météo de référence au Croisic est utilisée.
# Cela évite de multiplier les appels Open-Meteo lorsque l'on change de spot.
if zone_mode == "🧳 Déplacement / vacances" or use_spot_coords:
    lat_cible, lon_cible = spot["lat"], spot["lon"]
    st.sidebar.caption(
        "⚠️ Coordonnées exactes activées : peut générer une nouvelle requête API."
    )
else:
    lat_cible, lon_cible = CENTER["lat"], CENTER["lon"]
    st.sidebar.caption(
        f"Météo de référence : {CENTER['nom']} "
        f"({CENTER['lat']:.4f}, {CENTER['lon']:.4f})"
    )

# -----------------------------
# Contrôle des appels API
# -----------------------------
st.sidebar.divider()
force_refresh = False
if st.sidebar.button("🔄 Actualiser météo / mer"):
    fetch_weather.clear()
    fetch_marine.clear()
    force_refresh = True

# -----------------------------
# Chargement données (cache partagé Supabase)
# -----------------------------
with st.spinner("Chargement météo, mer et marées..."):
    df_weather = _fetch_weather_cached(lat_cible, lon_cible, force=force_refresh)
    df_marine = _fetch_marine_cached(lat_cible, lon_cible, force=force_refresh)

if df_weather.empty:
    st.error(
        "❌ Impossible de récupérer les données météo pour le moment. "
        "Open-Meteo a probablement limité l'adresse IP de l'hébergement."
    )
    st.info(
        "Attends quelques minutes puis clique sur **🔄 Actualiser météo / mer**. "
        "Laisse l'option « coordonnées exactes du spot » désactivée."
    )
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
    shom_ds=shom_ds,
    shom_reference=shom_reference,
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
tab_dashboard, tab_spots, tab_shom, tab_carnet, tab_stats, tab_sources = st.tabs(
    [
        "📊 Indice & créneaux",
        "🗺️ Carte & spots",
        "🌊 Courants SHOM",
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
# TAB SHOM
# ============================================================
with tab_shom:
    st.subheader("🌊 Courants de marée SHOM 2D")
    st.markdown(
        "Le SHOM fournit les composantes **U/V** du courant de surface pour les "
        "coefficients **45 et 95**, avec des échéances autour de la PM/BM. "
        "Pour un coefficient réel entre 45 et 95, V6 interpole uniquement ces "
        "deux situations, puis convertit U/V en vitesse et direction."
    )
    if shom_ds is None:
        st.info(
            "Importe le paquet **Courants de marée 2D** (.zip/.txt) dans la "
            "barre latérale. Le produit SHOM est annoncé comme gratuit et sous "
            "Licence Ouverte 2.0."
        )
        st.markdown("**Source SHOM :**")
        st.markdown("urlPage officielle SHOM — Courants de marée 2Dhttps://diffusion.shom.fr/marees/courants-de-maree/courants2d/courants-2d.html")
    else:
        st.success("Fichier SHOM chargé et disponible pour le calcul horaire.")
        if isinstance(shom_ds, dict) and shom_ds.get("kind") == "txt":
            st.write("Format : TXT SHOM")
            st.write("Points chargés :", len(shom_ds["data"]))
            st.dataframe(shom_ds["data"].head(20), use_container_width=True, hide_index=True)
        else:
            _ds = shom_ds["data"] if isinstance(shom_ds, dict) else shom_ds
            st.write("Format : NetCDF")
            st.write("Dimensions :", dict(_ds.sizes))
            st.write("Variables :", list(_ds.data_vars))

        # Affiche le courant calculé au meilleur créneau et quelques créneaux proches.
        if not df_score.empty:
            st.markdown("### Courant SHOM sur les meilleurs créneaux")
            rows = []
            for _, rr in df_score.sort_values("score", ascending=False).head(12).iterrows():
                ti = tides_dict.get(rr["date"], {})
                cur = shom_current_at(shom_ds, spot["lat"], spot["lon"], rr["datetime"], ti, reference=shom_reference)
                if cur:
                    rows.append({
                        "Créneau": rr["datetime"].strftime("%d/%m %H:%M"),
                        "Indice": rr["score"],
                        "Coef réel": cur["coef"],
                        "Courant": f"{cur['speed_kn']:.2f} nd",
                        "Direction": f"{cur['direction']:.0f}°",
                        "Δ PM/BM": f"{cur['delta_h']:+.1f} h",
                    })
            if rows:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            else:
                st.warning("Aucune valeur SHOM exploitable pour les créneaux affichés. Vérifie PM/BM et la zone couverte par le fichier.")

# ============================================================
# TAB 3 : carnet de sessions
# ============================================================
with tab_carnet:
    st.subheader("📖 Carnet de sessions")
    st.caption(
        "Une bredouille est une donnée utile : elle permet au moteur d'apprendre "
        "qu'un créneau apparemment favorable n'a pas forcément produit de poisson."
    )
    st.caption(
        "Stockage : Supabase (persistant, accessible depuis n'importe quel appareil)."
    )

    st.markdown("### ➕ Nouvelle session")

    c1, c2, c3 = st.columns(3)
    with c1:
        session_date = st.date_input("Date", value=date.today(), key="ns_date")
        session_species = st.selectbox(
            "Espèce ciblée",
            list(SPECIES.keys()),
            index=list(SPECIES.keys()).index(species),
            key="ns_species",
        )
        session_spot = st.selectbox(
            "Spot",
            spot_names,
            index=spot_names.index(selected_spot_name),
            key="ns_spot",
        )

    with c2:
        start_time = st.time_input("Début", key="ns_start")
        end_time = st.time_input("Fin", key="ns_end")
        session_technique = st.text_input("Technique / leurre", technique, key="ns_technique")

    with c3:
        touches = st.number_input("Touches", min_value=0, max_value=200, value=0, key="ns_touches")
        decroches = st.number_input("Décrochés", min_value=0, max_value=200, value=0, key="ns_decroches")
        coef_session = st.number_input("Coefficient", min_value=0, max_value=120, value=70, key="ns_coef")

    comment = st.text_area(
        "Observations",
        placeholder="Poste, fond, appât/leurre, animation, courant, comportement des poissons...",
        key="ns_comment",
    )

    st.markdown("#### 🐟 Poissons capturés")
    st.caption("Laisse le tableau vide pour enregistrer une bredouille. Une ligne = un poisson.")
    captures_df = st.data_editor(
        pd.DataFrame(
            columns=["espece", "heure", "taille_cm", "poids_kg", "leurre_appat", "observations"]
        ),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="ns_captures_editor",
        column_config={
            "espece": st.column_config.SelectboxColumn("Espèce", options=list(SPECIES.keys())),
            "heure": st.column_config.TextColumn("Heure (HH:MM)"),
            "taille_cm": st.column_config.NumberColumn("Taille (cm)", min_value=0.0, max_value=150.0),
            "poids_kg": st.column_config.NumberColumn("Poids (kg)", min_value=0.0, max_value=30.0),
            "leurre_appat": st.column_config.TextColumn("Leurre / appât"),
            "observations": st.column_config.TextColumn("Observations"),
        },
    )

    photos = st.file_uploader(
        "Photos (optionnel — associées aux captures ci-dessus, dans l'ordre des lignes)",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True,
        key="ns_photos",
    )

    if st.button("💾 Enregistrer la session", key="ns_submit", type="primary"):
        chosen = next(s for s in SPOTS if s["nom"] == session_spot)
        captures_rows = captures_df.dropna(how="all").to_dict(orient="records")

        photo_paths = []
        for i, f in enumerate(photos or []):
            fname = f"{session_date.strftime('%Y%m%d')}_{int(time.time())}_{i}_{f.name}"
            try:
                path = db.upload_photo(f.getvalue(), fname, f.type or "image/jpeg")
                photo_paths.append(path)
            except Exception as e:
                st.warning(f"Photo non envoyée ({f.name}) : {e}")
                photo_paths.append(None)

        captures_payload = []
        for i, c in enumerate(captures_rows):
            captures_payload.append({
                "espece": c.get("espece") or session_species,
                "heure": (c.get("heure") or "").strip() or None,
                "taille_cm": safe_float(c.get("taille_cm")),
                "poids_kg": safe_float(c.get("poids_kg")),
                "leurre_appat": c.get("leurre_appat"),
                "technique": session_technique,
                "photo_url": photo_paths[i] if i < len(photo_paths) else None,
                "observations": c.get("observations"),
            })

        session_row = {
            "date": session_date.strftime("%Y-%m-%d"),
            "heure_debut": start_time.strftime("%H:%M"),
            "heure_fin": end_time.strftime("%H:%M"),
            # Référence aux 10 spots préconfigurés (ou à un secteur "custom_..."
            # en mode vacances) — ce n'est PAS une clé étrangère vers la table
            # `spots` Supabase, qui elle sert aux spots personnels additionnels.
            "spot_id": chosen["id"],
            "spot_nom": chosen["nom"],
            "espece_ciblee": session_species,
            "technique": session_technique,
            "conditions": {"maree": {"coefficient": int(coef_session)}},
            "nb_poissons": len(captures_payload),
            "touches": int(touches),
            "decroches": int(decroches),
            "commentaire": comment,
        }

        try:
            db.save_session(session_row, captures_payload)
            st.success("✅ Session enregistrée.")
            st.rerun()
        except Exception as e:
            st.error(f"Erreur d'enregistrement : {e}")

    st.divider()
    st.markdown("### 📚 Historique")

    if sessions_data:
        df_c = pd.DataFrame(sessions_data)[
            ["date", "heure_debut", "heure_fin", "espece_ciblee", "spot_nom",
             "technique", "nb_poissons", "touches", "decroches", "commentaire"]
        ]
        st.dataframe(df_c, use_container_width=True, hide_index=True)

        b1, b2 = st.columns(2)
        with b1:
            options = {
                s["id"]: f"{s['date']} — {s['spot_nom']} ({s['espece_ciblee']})"
                for s in sessions_data
            }
            to_delete = st.selectbox(
                "Session à supprimer",
                options=list(options.keys()),
                format_func=lambda i: options[i],
                key="del_select",
            )
            if st.button("🗑️ Supprimer cette session"):
                db.delete_session(to_delete)
                st.rerun()
        with b2:
            st.download_button(
                "⬇️ Exporter le carnet (JSON)",
                data=db.export_carnet_json(),
                file_name="carnet_peche_export.json",
                mime="application/json",
            )
    else:
        st.info("Aucune session enregistrée.")

# ============================================================
# TAB 4 : statistiques personnelles
# ============================================================
with tab_stats:
    st.subheader("🧠 Analyse personnelle")

    if not sessions_data:
        st.warning("Enregistre au moins quelques sessions pour commencer l'apprentissage.")
    else:
        df_s = pd.DataFrame(sessions_data)
        df_s["coef"] = df_s["conditions"].apply(
            lambda c: safe_float(((c or {}).get("maree") or {}).get("coefficient"))
        )
        df_s["prise"] = pd.to_numeric(df_s["nb_poissons"], errors="coerce").fillna(0) > 0

        df_cap = pd.DataFrame(captures_data) if captures_data else pd.DataFrame(
            columns=["session_id", "espece", "taille_cm", "poids_kg"]
        )

        total_sessions = len(df_s)
        successful = int(df_s["prise"].sum())
        success_rate = successful / total_sessions * 100 if total_sessions else 0

        m1, m2, m3 = st.columns(3)
        m1.metric("Sessions", total_sessions)
        m2.metric("Sessions avec poisson", successful)
        m3.metric("Taux de réussite", f"{success_rate:.0f}%")

        st.markdown("### 🐟 Résultats par espèce")
        grp = (
            df_s.groupby("espece_ciblee")
            .agg(
                sessions=("prise", "size"),
                sessions_avec_poisson=("prise", "sum"),
                poissons=("nb_poissons", "sum"),
                coef_moyen=("coef", "mean"),
            )
            .reset_index()
            .rename(columns={"espece_ciblee": "espece"})
        )
        grp["taux_reussite_%"] = (
            grp["sessions_avec_poisson"] / grp["sessions"] * 100
        ).round(1)
        st.dataframe(grp, use_container_width=True, hide_index=True)

        if not df_cap.empty:
            st.markdown("### 📏 Tailles / poids par espèce capturée")
            cap_grp = (
                df_cap.assign(
                    taille_cm=pd.to_numeric(df_cap["taille_cm"], errors="coerce"),
                    poids_kg=pd.to_numeric(df_cap["poids_kg"], errors="coerce"),
                )
                .groupby("espece")
                .agg(
                    poissons=("id", "count"),
                    taille_moy_cm=("taille_cm", "mean"),
                    taille_max_cm=("taille_cm", "max"),
                    poids_moy_kg=("poids_kg", "mean"),
                    poids_max_kg=("poids_kg", "max"),
                )
                .round(1)
                .reset_index()
            )
            st.dataframe(cap_grp, use_container_width=True, hide_index=True)

        st.markdown("### 🗺️ Tes spots les plus rentables")
        spot_grp = (
            df_s.groupby(["spot_nom", "espece_ciblee"])
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
        coef_valid = df_s.dropna(subset=["coef"])
        if not coef_valid.empty:
            coef_grp = (
                coef_valid.groupby(pd.cut(
                    coef_valid["coef"],
                    bins=[0, 45, 60, 75, 90, 105, 120],
                    include_lowest=True,
                ))
                .agg(
                    sessions=("prise", "size"),
                    sessions_avec_poisson=("prise", "sum"),
                )
                .reset_index()
            )
            coef_grp["taux_reussite_%"] = (
                coef_grp["sessions_avec_poisson"]
                / coef_grp["sessions"] * 100
            ).round(1)
            st.dataframe(coef_grp, use_container_width=True, hide_index=True)
        else:
            st.caption("Pas encore de coefficient renseigné sur tes sessions.")

        st.info(
            "ℹ️ Le moteur V6 utilise actuellement un lissage statistique simple. "
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

### Stockage
- Carnet (sessions + captures + photos) : Supabase, persistant et privé
  (RLS), accessible depuis n'importe quel appareil connecté à ton compte.
- Données SHOM et météo/marine prétraitées : cache partagé Supabase, pour
  éviter de retraiter le ZIP SHOM ou de rappeler les API à chaque lancement.
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
    cfg1, cfg2 = st.columns(2)
    with cfg1:
        if API_KEY_MAREE:
            st.success("API_KEY_MAREE détectée.")
        else:
            st.error("API_KEY_MAREE absente.")
    with cfg2:
        try:
            db.get_client()
            st.success("Connexion Supabase OK.")
        except Exception as e:
            st.error(f"Supabase non configuré : {e}")

# -----------------------------
# Footer
# -----------------------------
st.divider()
st.caption(
    "Indice Pêche V6.2 — outil d'aide à la décision. "
    "Un score élevé indique une combinaison de conditions plus proche "
    "des hypothèses du modèle ; il ne garantit pas une prise."
)