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
import numpy as np
import plotly.graph_objects as go
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
        # poids : marée/courant/vent/houle/lumière/eau/pression/historique/pluie
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

# "Daurade royale".lower().replace(" ", "_") donnerait "daurade_royale", qui
# n'existe pas dans les dicts SPOTS/spot personnalisé (clé "daurade" seule)
# — d'où le KeyError. Mapping explicite plutôt qu'une dérivation implicite
# fragile.
SPECIES_SPOT_KEY = {"Bar": "bar", "Daurade royale": "daurade"}

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
    x = float(x)
    if math.isnan(x):
        # Python : min(hi, nan) vaut silencieusement hi (pas nan), ce qui
        # forcerait un score manquant/invalide au MAXIMUM au lieu de le
        # signaler. On retourne plutôt une valeur neutre au milieu de
        # l'échelle, cohérente avec les autres valeurs par défaut (5.0)
        # utilisées ailleurs dans le moteur de score.
        return (lo + hi) / 2
    return max(lo, min(hi, x))


# Échelle de couleur partagée par TOUS les éléments colorés de l'interface
# (tableaux, pastilles des boutons de jour, badges de détail) :
# ≤50 = rouge plein (mauvais), 75 = vert léger, ≥90 = vert plein (excellent),
# dégradé continu rouge → orange → vert clair → vert entre les paliers.
def _mix_rgb(c1, c2, t):
    return tuple(round(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def score_rgb_100(v):
    v = max(0.0, min(100.0, float(v)))
    RED, ORANGE, LGREEN, GREEN = (211, 47, 47), (245, 124, 0), (139, 195, 74), (56, 142, 60)
    if v <= 50:
        return RED
    if v <= 62:
        return _mix_rgb(RED, ORANGE, (v - 50) / 12)
    if v <= 75:
        return _mix_rgb(ORANGE, LGREEN, (v - 62) / 13)
    if v <= 90:
        return _mix_rgb(LGREEN, GREEN, (v - 75) / 15)
    return GREEN


def score_css_100(val):
    """Couleur de fond pour une note sur 100, dégradé continu rouge→orange→vert."""
    try:
        v = float(val)
    except Exception:
        return ""
    if math.isnan(v):
        return ""
    r, g, b = score_rgb_100(v)
    return f"background-color:rgb({r},{g},{b});color:#ffffff"


# Échelle simple (bandes, pas de dégradé) pour un cumul de pluie JOURNALIER
# en mm. Calibrée sur la classification OMM de l'intensité horaire (faible
# < 2 mm/h, modérée 2-7,6 mm/h, forte > 7,6 mm/h) et sur le repère français
# de cumul "abondant" à partir de 40 mm/24h, ramenés à une tolérance
# personnelle : de faibles averses restent vertes, au-delà ça devient rouge.
def rain_mm_css(val):
    try:
        v = float(val)
    except Exception:
        return ""
    if math.isnan(v):
        return ""
    if v <= 3:
        return "background-color:#43a047;color:#ffffff"
    if v <= 10:
        return "background-color:#ff9800;color:#ffffff"
    return "background-color:#e53935;color:#ffffff"


def styled_score_table(df, columns, rain_column=None):
    """Applique score_css_100 sur une ou plusieurs colonnes (Indice, heures),
    et rain_mm_css sur la colonne de pluie journalière le cas échéant.
    Compatible Styler.map (pandas >= 2.1) et l'ancien Styler.applymap.
    Formate aussi l'affichage (0 décimale pour les scores, 1 pour la pluie) :
    sans .format() explicite, Styler affiche la précision flottante brute
    (ex. "78.200000" au lieu de "78").
    """
    if isinstance(columns, str):
        columns = [columns]
    styler = df.style
    mapper = styler.map if hasattr(styler, "map") else styler.applymap
    styler = mapper(score_css_100, subset=columns)
    fmt = {c: "{:.0f}" for c in columns}
    if rain_column and rain_column in df.columns:
        mapper2 = styler.map if hasattr(styler, "map") else styler.applymap
        styler = mapper2(rain_mm_css, subset=[rain_column])
        fmt[rain_column] = "{:.1f}"
    # Format par défaut (1 décimale) pour toute colonne numérique non listée
    # ci-dessus, avant d'appliquer les formats spécifiques : évite le même
    # problème de précision flottante brute sur des colonnes comme "Coef".
    styler = styler.format(precision=1, na_rep="—")
    styler = styler.format(fmt, na_rep="—")
    return styler


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


def pressure_score(pressure, d3, d6, d12, d24=None):
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

    # Fenêtre de repos post-hausse (24-48h) : une forte hausse de pression sur
    # les dernières 24h laisse les poissons "calés" quelques temps même une
    # fois la tendance instantanée (6h) redevenue stable — la doc décrit
    # cette baisse d'activité comme un phénomène de 24 à 48h, pas juste un
    # état instantané. On ne pénalise que si la tendance 6h ne signale déjà
    # pas elle-même une hausse nette (sinon double comptage).
    recovery_note = ""
    if d24 is not None and d24 >= 4 and -0.7 <= trend < 2:
        s -= 1.5
        recovery_note = " — repos post-hausse (24h)"

    return clamp(s), f"{pressure:.1f} hPa — {label}{recovery_note} ({trend:+.1f} hPa/6h)"


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


def turbidity_index(wave_h, precip_mm_h):
    """Estimation grossière (0=eau claire, 10=eau très trouble) à partir de la
    houle et de la pluie de l'heure — pas une mesure directe (aucune source
    météo utilisée ne fournit la turbidité réelle). Sert à moduler l'effet du
    grand soleil sur la méfiance du poisson (eau déjà trouble = la lumière de
    surface pénètre moins, donc l'effet est déjà partiellement neutralisé) et
    à orienter le choix de couleur de leurre dans recommendation_for().
    """
    wave_h = wave_h or 0.0
    precip_mm_h = precip_mm_h or 0.0
    return clamp(wave_h * 3.0 + precip_mm_h * 1.5, 0, 10)


def light_score(dt_local, cloud, species, turbidity=None):
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
        # Eau déjà trouble (houle/pluie) : la lumière de surface pénètre
        # moins, donc la pénalité "grand soleil" compte moins — pas une
        # nouvelle pondération indépendante (éviterait un double comptage
        # avec les poids houle/pluie déjà présents dans le score global),
        # juste une atténuation d'un effet déjà modélisé ici.
        sun_penalty_scale = 1.0
        if turbidity is not None and turbidity >= 5:
            sun_penalty_scale = 0.4

        if 20 <= cloud <= 75:
            # Couvert léger à modéré : lumière diffuse, souvent plus
            # favorable qu'un grand soleil (moins de méfiance du poisson).
            base += 0.6
        elif cloud < 15:
            # Ciel bien dégagé / grand soleil : lumière crue.
            base -= 0.4 * sun_penalty_scale
        elif cloud > 90:
            base -= 0.3

    return clamp(base), "Transition lumineuse" if transition else "Lumière standard"


def rain_penalty(precip_mm):
    """Facteur MULTIPLICATIF appliqué au score final (pas une simple
    moyenne pondérée) : la pluie est un critère quasi rédhibitoire —
    diluée dans une moyenne avec 8-9 autres facteurs, elle perdrait
    trop d'impact même sous forte pluie. Ici, un temps pluvieux tire le
    score final vers le bas quelle que soit la qualité des autres
    conditions.
    """
    if precip_mm is None:
        return 1.0, "Pluie indisponible"

    p = float(precip_mm)
    if p <= 0.05:
        return 1.0, "Temps sec"
    elif p <= 0.5:
        return 0.9, f"Bruine ({p:.1f} mm/h)"
    elif p <= 2.0:
        return 0.55, f"Pluie légère ({p:.1f} mm/h)"
    elif p <= 5.0:
        return 0.3, f"Pluie modérée ({p:.1f} mm/h)"
    else:
        return 0.15, f"Forte pluie ({p:.1f} mm/h)"


def continuous_coef_score(coef, species):
    if coef is None:
        return 5.0
    c = float(coef)

    if species == "Daurade royale":
        # La documentation trouvée est partagée entre deux écoles : morte-eau
        # (coefficient bas, pêche au posé prolongée, pic documenté ~50) et
        # gros coefficient (daurade plus agressive, pic documenté ~95). Plutôt
        # que trancher arbitrairement, on retient le meilleur des deux
        # courbes — un creux réel autour de 70-75 (coefficient moyen, ni
        # franchement morte-eau ni vive-eau) reste correct sans être optimal.
        s_morte_eau = 10 - abs(c - 50) / 10
        s_vive_eau = 10 - abs(c - 95) / 10
        return clamp(max(s_morte_eau, s_vive_eau))
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


def _to_paris_aware(ts):
    """Convertit un Timestamp en horaire Europe/Paris. S'il est déjà
    localisé (autre fuseau), on le convertit ; s'il est naïf (cas des
    horaires météo Open-Meteo), on suppose qu'il représente déjà une
    heure locale Europe/Paris, comme le reste de l'application.
    Évite les TypeError lors de la comparaison/soustraction entre
    horaires météo (naïfs) et horaires de marée (localisés).
    """
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        return ts.tz_localize("Europe/Paris")
    return ts.tz_convert("Europe/Paris")


def tide_phase_score(dt, extrema, species):
    """Retourne score, description, phase, distance au dernier événement."""
    if not extrema:
        return 5.0, "Marée indisponible", "Inconnue", None

    # `dt` (météo Open-Meteo) est naïf, tandis que parse_extreme_datetime()
    # localise les horaires de marée en Europe/Paris : on aligne les deux
    # pour permettre la comparaison.
    dt = _to_paris_aware(dt)

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

    # Bonus explicite ±2h autour du pic de marée (PM ou BM, avant ou après) :
    # la doc cite spécifiquement cette fenêtre comme celle du courant maximal,
    # en plus du score de phase ci-dessus qui raisonne en % du cycle.
    minutes_to_next = (nxt[0] - dt).total_seconds() / 60
    minutes_since_prev = (dt - prev[0]).total_seconds() / 60
    near_peak = minutes_to_next <= 120 or minutes_since_prev <= 120
    if near_peak:
        s += 0.5

    peak_note = " · pic à ±2h" if near_peak else ""
    return clamp(s), f"{phase} — prochaine {nxt[1]} à {nxt[0].strftime('%H:%M')}{peak_note}", phase, minutes_to_next


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


BAR_TECHNIQUE_PROFILE = {
    "Surface": {
        "depth": "surface",
        "channel": "vue (silhouette, sillage)",
        "speed": "vive, pauses marquées",
    },
    "Métal": {
        "depth": "pleine eau à fond, prospection large",
        "channel": "flash + vibration",
        "speed": "rapide, ramené linéaire ou saccadé",
    },
    "Jerkbait / minnow": {
        "depth": "sub-surface (20–60 cm)",
        "channel": "imitation visuelle + rolling",
        "speed": "lente à modérée, tirées-pauses",
    },
    "Leurre souple": {
        "depth": "mi-eau à fond, suit la dérive",
        "channel": "vibration de caudale (ligne latérale)",
        "speed": "adaptée au courant, animation près du fond",
    },
}
DAURADE_TECHNIQUE_PROFILE = {
    "Crabe au posé": {
        "appat": "crabe vert (dur ou mou)",
        "montage": "coulissant 50–80 g, fluoro 40–45/100, bas de ligne 1–1,5 m, hameçon fort n°1–2",
        "note": "très sélectif, cible plutôt les belles pièces",
    },
    "Couteau / coquillage": {
        "appat": "couteau ou coquillage décortiqué",
        "montage": "coulissant 50–80 g",
        "note": "efficace sur fonds sableux, post-marée",
    },
    "Ver": {
        "appat": "ver marin (arénicole/américain)",
        "montage": "coulissant léger à moyen",
        "note": "plus universel, davantage de touches mais moins sélectif",
    },
    "Surfcasting": {
        "appat": "appât naturel au choix selon le fond",
        "montage": "coulissant léger, 60–90 g selon courant",
        "note": "prospection large en battant l'estran",
    },
}


def recommendation_for(species, technique, score, row, spot):
    """Recommandation dynamique : la couleur/canal sensoriel privilégié varie
    avec la turbidité estimée (eau claire → discret/visuel, eau trouble →
    vibrant/voyant, s'appuie sur la ligne latérale), et l'animation varie
    avec la température de l'eau (froide → lente, éviter la surface sous
    ~14°C pour le bar). Chaque technique a un profil propre (profondeur,
    canal sensoriel, vitesse) pour que la recommandation principale et son
    alternative restent réellement différenciées plutôt que de simples
    reformulations l'une de l'autre. Sources : voir recherche_criteres_peche.md.
    """
    turb = row.get("turbidity_idx") if hasattr(row, "get") else None
    sst = row.get("water_temp_c") if hasattr(row, "get") else None
    cold_water = sst is not None and sst < 14

    if species == "Bar":
        profile = BAR_TECHNIQUE_PROFILE.get(technique, BAR_TECHNIQUE_PROFILE["Leurre souple"])

        if cold_water and technique == "Surface":
            return (
                "Eau <14°C : la surface devient peu productive (le bar évolue "
                "plus profond) — bascule sur un poisson nageur ou un leurre "
                "souple en mi-eau, animation lente."
            )

        speed = f"{profile['speed']}, ralentie (eau froide)" if cold_water else profile["speed"]

        if turb is not None and turb >= 6:
            couleur = f"coloris vif (chartreuse, blanc, UV) — mise sur {profile['channel']}"
        elif turb is not None and turb <= 2:
            couleur = f"coloris naturel/translucide, joue sur {profile['channel']}"
        else:
            couleur = f"coloris intermédiaire, {profile['channel']}"

        return (
            f"{technique} — évolue en {profile['depth']} ; {couleur} ; "
            f"animation {speed}."
        )
    else:
        profile = DAURADE_TECHNIQUE_PROFILE.get(technique, DAURADE_TECHNIQUE_PROFILE["Surfcasting"])
        base = f"{profile['appat']}, montage {profile['montage']} — {profile['note']}."

        if turb is not None and turb <= 2:
            base += " Eau claire : affine le bas de ligne (22/100) et reste discret, la daurade est méfiante."
        elif turb is not None and turb >= 6:
            base += " Mer agitée/eau trouble : privilégie un appât résistant (crabe dur, bibi)."
        return base



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


KNOT_TO_MS = 0.5144447


def _parse_shom_position(token):
    """Convertit un jeton de coordonnée SHOM (format sDDMM.mmm pour la
    latitude, sDDDMM.mmm pour la longitude) en degrés décimaux. Les 2
    derniers chiffres avant le point décimal sont toujours les minutes, le
    reste les degrés — valable aussi bien pour la latitude (2 chiffres de
    degrés) que la longitude (jusqu'à 3 chiffres), sans distinction requise.
    """
    token = token.strip()
    if not token or "." not in token:
        return None
    sign = 1.0
    if token[0] == "-":
        sign = -1.0
        token = token[1:]
    elif token[0] == "+":
        token = token[1:]
    whole, frac = token.split(".", 1)
    if len(whole) < 2:
        return None
    try:
        minutes = float(whole[-2:] + "." + frac)
        degrees = float(whole[:-2]) if whole[:-2] else 0.0
    except ValueError:
        return None
    return sign * (degrees + minutes / 60.0)


def _align_shom_field_block(segment, strip_side):
    """Ramène un bloc de valeurs à un multiple de 3 caractères en ne
    retirant que de VRAIS espaces du côté attendu (bordure du séparateur
    '*'). Le nombre d'espaces autour du '*' varie ligne à ligne dans les
    fichiers réels — il n'y en a parfois aucun, parfois un — selon que la
    valeur adjacente a elle-même besoin d'un espace de remplissage dans
    son propre champ de 3 caractères. Un simple rstrip()/lstrip() retire
    parfois à tort un espace qui appartient à une valeur, décalant tout le
    reste du découpage. Confirmé caractère par caractère sur des fichiers
    SHOM réels (aucun échec sur 557/BOULOGNE, CALAIS, DUNKERQUE, PAS_DE_CALAIS).
    """
    while len(segment) % 3 != 0 and segment and (
        (segment[-1] == " ") if strip_side == "right" else (segment[0] == " ")
    ):
        segment = segment[:-1] if strip_side == "right" else segment[1:]
    return segment if len(segment) % 3 == 0 else None


def _chunk_shom_values(segment):
    """Découpe une chaîne en blocs fixes de 3 caractères (format officiel
    SHOM confirmé sur données réelles : chaque valeur, en dixièmes de
    nœud, occupe exactement 3 caractères, signe compris — le blanc n'est
    PAS un séparateur, contrairement à un format tabulaire classique).
    Retourne None si le découpage n'est pas net (protection contre un
    fichier qui ne suivrait pas ce format).
    """
    if len(segment) % 3 != 0:
        return None
    vals = []
    for i in range(0, len(segment), 3):
        piece = segment[i:i + 3].strip()
        if piece in ("", "-"):
            vals.append(None)
            continue
        try:
            vals.append(int(piece))
        except ValueError:
            return None
    return vals


def _parse_shom_txt_official(raw, filename="courants.txt"):
    """Lit le format officiel SHOM 'Courants de marée des côtes de France'
    (documenté dans le _lisezmoi.txt du CD-ROM, confirmé caractère par
    caractère sur des fichiers réels) :
    - en-tête : nom du port de référence (suffixe .BM si basse mer, sinon
      pleine mer implicite) ;
    - puis des triplets de 3 lignes par point : position WGS84, courants
      de vive-eau (coefficient 95), courants de morte-eau (coefficient 45) ;
    - 13 échéances de -6h à +6h par rapport à la PM/BM, EN DIXIÈMES DE
      NŒUD (converties ici en m/s — l'ancien code les traitait à tort
      comme des m/s bruts, soit un facteur ~19 d'erreur).
    Ce N'EST PAS un tableau colonnes/lignes classique : impossible à lire
    avec un simple séparateur, d'où cette lecture positionnelle dédiée.
    """
    text = raw.decode("latin-1", errors="replace")
    raw_lines = [l.rstrip("\r").rstrip("\t") for l in text.splitlines()]
    lines = [l for l in raw_lines if l.strip() != ""]
    if not lines:
        raise ValueError("Fichier SHOM vide.")

    header = lines[0].strip()
    reference = "PM"
    port = header
    if port.upper().endswith(".BM"):
        reference = "BM"
        port = port[:-3].strip()

    hours = list(range(-6, 7))
    rows = []
    i = 1
    n = len(lines)
    while i + 2 < n:
        parts = lines[i].split()
        if len(parts) < 2:
            i += 1
            continue
        lat = _parse_shom_position(parts[0])
        lon = _parse_shom_position(parts[1])
        if lat is None or lon is None:
            i += 1
            continue

        ok = True
        point_rows = []
        for coef, line in ((95, lines[i + 1]), (45, lines[i + 2])):
            if "*" not in line:
                ok = False
                break
            we_part, ns_part = line.split("*", 1)
            we_aligned = _align_shom_field_block(we_part, "right")
            ns_aligned = _align_shom_field_block(ns_part, "left")
            if we_aligned is None or ns_aligned is None:
                ok = False
                break
            we_vals = _chunk_shom_values(we_aligned)
            ns_vals = _chunk_shom_values(ns_aligned)
            if we_vals is None or ns_vals is None or len(we_vals) != 13 or len(ns_vals) != 13:
                ok = False
                break
            for h, u_raw, v_raw in zip(hours, we_vals, ns_vals):
                if u_raw is None or v_raw is None:
                    continue
                point_rows.append({
                    "lat": lat, "lon": lon, "offset_h": h, "coefficient": coef,
                    "u": (u_raw / 10.0) * KNOT_TO_MS,
                    "v": (v_raw / 10.0) * KNOT_TO_MS,
                })
        if ok:
            rows.extend(point_rows)
        i += 3

    if not rows:
        raise ValueError(
            "Aucun point exploitable — le fichier ne correspond pas au format "
            "officiel SHOM (en-tête = port, puis triplets position / "
            "vive-eau / morte-eau)."
        )

    df = pd.DataFrame(rows)
    df["phase"] = reference
    df["source_file"] = filename
    df["port_reference"] = port
    return df


def load_shom_dataset(uploaded_file):
    """Charge soit le NetCDF 2D, soit le TXT/ZIP du produit SHOM.

    Les fichiers officiels SHOM (ex. CALAIS_557, BOULOGNE_557) n'ont AUCUNE
    extension — on ne filtre donc plus sur ".txt" dans un ZIP : on tente le
    parseur officiel sur chaque membre et on ignore silencieusement ceux qui
    échouent (fichiers d'aide _lisezmoi*, .ico, .rtf...).
    """
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

    # ZIP : le dossier SHOM complet (fichiers de données sans extension +
    # fichiers d'aide _lisezmoi*.txt à ignorer).
    if name.endswith(".zip"):
        try:
            z = zipfile.ZipFile(BytesIO(raw))
            frames = []
            for info in z.infolist():
                if info.is_dir():
                    continue
                base = info.filename.rsplit("/", 1)[-1]
                if base.lower().startswith("_lisezmoi") or base.lower().endswith((".ico", ".rtf", ".gif")):
                    continue
                try:
                    d = _parse_shom_txt_official(z.read(info), base)
                    frames.append(d)
                except Exception:
                    continue
            if not frames:
                raise ValueError("Aucun fichier SHOM exploitable trouvé dans le ZIP.")
            return {"kind": "txt", "data": pd.concat(frames, ignore_index=True)}, None
        except Exception as e:
            return None, str(e)

    # TXT nommé explicitement, ou fichier de données SHOM sans extension
    # (cas normal pour un fichier téléchargé individuellement).
    try:
        df = _parse_shom_txt_official(raw, uploaded_file.name)
        return {"kind": "txt", "data": df}, None
    except Exception as e:
        return None, str(e)


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
            et = pd.Timestamp(e["time"])
            typ = str(e.get("type", "")).upper()
            if reference == "PM" and "PM" not in typ:
                continue
            if reference == "BM" and "BM" not in typ:
                continue
            delta_h = (_to_paris_aware(dt) - _to_paris_aware(et)).total_seconds() / 3600.0
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
            et=pd.Timestamp(e["time"]); typ=str(e.get("type","")).upper()
            if reference == "PM" and "PM" not in typ: continue
            if reference == "BM" and "BM" not in typ: continue
            dh=(_to_paris_aware(dt)-_to_paris_aware(et)).total_seconds()/3600
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


def shom_field_at_hour(shom_ds, tides_dict, date_key, hour_int, reference, lat_center, lon_center, radius_km=15.0):
    """Champ de courant 2D (tous les points SHOM proches du spot) pour une
    heure donnée d'un jour donné. Contrairement à shom_current_txt() qui ne
    donne qu'UN point, ceci reconstruit la grille entière pour la carte
    animée : pour chaque point, on sélectionne l'échéance (offset_h) la plus
    proche de l'heure demandée séparément pour les situations coefficient 45
    et 95, puis on interpole entre les deux comme pour le score.
    Ne fonctionne qu'avec le format TXT/ZIP (pas encore le NetCDF).
    """
    if not (isinstance(shom_ds, dict) and shom_ds.get("kind") == "txt"):
        return None, "Visualisation disponible uniquement pour le format TXT/ZIP pour l'instant."

    df_pts = shom_ds["data"]
    if df_pts.empty or df_pts["coefficient"].isna().all():
        return None, "Le fichier ne contient pas de colonne coefficient exploitable."

    extrema = _extrema_window(tides_dict, date_key)
    tide_info = tides_dict.get(date_key, {})
    if not extrema:
        return None, "Pas de données de marée pour ce jour (nécessaires pour situer l'échéance PM/BM)."
    coef = safe_float(tide_info.get("max_coef"), 70)

    dt = _to_paris_aware(pd.Timestamp(f"{date_key} {hour_int:02d}:00:00"))
    candidates = []
    for e in extrema:
        et = parse_extreme_datetime(e)
        if et is None:
            continue
        typ = str(e.get("type", "")).upper()
        if reference == "PM" and "PM" not in typ:
            continue
        if reference == "BM" and "BM" not in typ:
            continue
        dh = (dt - et).total_seconds() / 3600.0
        if -6.01 <= dh <= 6.01:
            candidates.append((abs(dh), dh))
    if not candidates:
        return None, f"Aucune échéance PM/BM ({reference}) à ±6h de {hour_int:02d}:00 ce jour-là."
    _, dh = min(candidates)

    def nearest_offset_subset(coeff_val):
        sub = df_pts[df_pts["coefficient"].sub(coeff_val).abs() < 1e-6]
        if sub.empty:
            return sub
        if sub["offset_h"].notna().any():
            available = sub["offset_h"].dropna().unique()
            nearest_off = min(available, key=lambda o: abs(o - dh))
            sub = sub[sub["offset_h"].sub(nearest_off).abs() < 1e-6]
        return sub

    d45 = nearest_offset_subset(45.0)
    d95 = nearest_offset_subset(95.0)
    if d45.empty or d95.empty:
        return None, "Situations coefficient 45/95 introuvables dans le fichier pour cette échéance."

    merged = d45.merge(d95, on=["lat", "lon"], suffixes=("_45", "_95"), how="inner")
    if merged.empty:
        return None, "Grilles 45 et 95 non superposables (points non alignés)."

    target = max(45.0, min(95.0, float(coef)))
    alpha = (target - 45.0) / 50.0
    merged["u"] = merged["u_45"] + alpha * (merged["u_95"] - merged["u_45"])
    merged["v"] = merged["v_45"] + alpha * (merged["v_95"] - merged["v_45"])

    merged["dist_km"] = merged.apply(
        lambda r: haversine(lat_center, lon_center, r["lat"], r["lon"]), axis=1
    )
    merged = merged[merged["dist_km"] <= radius_km]
    if merged.empty:
        return None, f"Aucun point SHOM à moins de {radius_km:.0f} km du spot."

    merged["speed_kn"] = np.hypot(merged["u"], merged["v"]) * 1.943844
    merged["direction"] = (np.degrees(np.arctan2(merged["u"], merged["v"])) + 360) % 360
    return merged[["lat", "lon", "u", "v", "speed_kn", "direction"]].reset_index(drop=True), None


def build_current_arrows_figure(hourly_fields, hours, center_lat, center_lon, arrow_scale=0.006):
    """Construit une figure Plotly (fond OpenStreetMap, pas de clé requise)
    avec une flèche par point de grille et une frame par heure, pour le
    lecteur d'animation (play/pause + curseur) de l'onglet SHOM.
    """
    def frame_traces(field_df):
        if field_df is None or field_df.empty:
            return [go.Scattermapbox(lat=[], lon=[], mode="lines"),
                    go.Scattermapbox(lat=[], lon=[], mode="markers")]
        lats, lons = [], []
        for _, r in field_df.iterrows():
            length = r["speed_kn"] * arrow_scale
            rad = math.radians(r["direction"])
            dlat = length * math.cos(rad)
            dlon = length * math.sin(rad) / max(0.2, math.cos(math.radians(r["lat"])))
            lats += [r["lat"], r["lat"] + dlat, None]
            lons += [r["lon"], r["lon"] + dlon, None]
        line_trace = go.Scattermapbox(
            lat=lats, lon=lons, mode="lines",
            line=dict(width=2, color="#1565c0"),
            hoverinfo="skip", showlegend=False,
        )
        tip_trace = go.Scattermapbox(
            lat=field_df["lat"] + field_df["speed_kn"] * arrow_scale * np.cos(np.radians(field_df["direction"])),
            lon=field_df["lon"] + field_df["speed_kn"] * arrow_scale * np.sin(np.radians(field_df["direction"])) / max(0.2, math.cos(math.radians(center_lat))),
            mode="markers",
            marker=dict(size=7, color=field_df["speed_kn"], colorscale="Turbo", cmin=0, cmax=3,
                        colorbar=dict(title="nd")),
            text=[f"{s:.2f} nd · {d:.0f}°" for s, d in zip(field_df["speed_kn"], field_df["direction"])],
            hoverinfo="text", showlegend=False,
        )
        return [line_trace, tip_trace]

    first_field = hourly_fields.get(hours[0])
    init_traces = frame_traces(first_field)

    frames = [
        go.Frame(data=frame_traces(hourly_fields.get(h)), name=f"{h:02d}h")
        for h in hours
    ]

    fig = go.Figure(data=init_traces, frames=frames)
    fig.update_layout(
        mapbox=dict(style="open-street-map", center=dict(lat=center_lat, lon=center_lon), zoom=10.5),
        margin=dict(l=0, r=0, t=0, b=0),
        height=520,
        updatemenus=[dict(
            type="buttons", showactive=False, x=0.02, y=0.02, xanchor="left", yanchor="bottom",
            buttons=[
                dict(label="▶️ Lecture", method="animate",
                     args=[None, {"frame": {"duration": 450, "redraw": True}, "fromcurrent": True, "mode": "immediate"}]),
                dict(label="⏸️ Pause", method="animate",
                     args=[[None], {"frame": {"duration": 0, "redraw": False}, "mode": "immediate"}]),
            ],
        )],
        sliders=[dict(
            active=0,
            currentvalue={"prefix": "Heure : "},
            steps=[dict(label=f"{h:02d}h", method="animate",
                        args=[[f"{h:02d}h"], {"frame": {"duration": 0, "redraw": True}, "mode": "immediate"}])
                   for h in hours],
        )],
    )
    return fig



    """Concatène les extrema de la veille, du jour et du lendemain, pour
    permettre à tide_phase_score()/shom_current_at() d'encadrer correctement
    les heures proches de minuit (continuité entre jours au lieu de se
    limiter aux seuls événements du jour, ce qui produisait des 'Phase
    incomplète' près des bornes de journée).
    """
    try:
        d = pd.Timestamp(date_key).date()
    except Exception:
        return tides_dict.get(date_key, {}).get("extrema", [])

    keys = [
        (d - timedelta(days=1)).strftime("%Y-%m-%d"),
        date_key,
        (d + timedelta(days=1)).strftime("%Y-%m-%d"),
    ]
    combined = []
    for k in keys:
        combined.extend(tides_dict.get(k, {}).get("extrema", []))
    return combined


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
        coef = safe_float(tide_info.get("max_coef"), 70)
        # Fenêtre étendue (veille/jour/lendemain) pour un encadrement PM/BM
        # fiable même en tout début ou toute fin de journée.
        extrema = _extrema_window(tides_dict, date_key)
        tide_info_window = {**tide_info, "extrema": extrema}

        phase_s, phase_desc, phase, _ = tide_phase_score(dt, extrema, species)
        coef_s = continuous_coef_score(coef, species)

        wind_s, wind_desc = wind_to_score(
            safe_float(r.get("wind_speed_10m")),
            safe_float(r.get("wind_direction_10m")),
            species,
        )
        wave_h_val = safe_float(r.get("wave_height"))
        wave_s, wave_desc = wave_score(
            wave_h_val,
            safe_float(r.get("wave_period")),
            species,
            spot,
        )
        pressure_s, pressure_desc = pressure_score(
            safe_float(r.get("surface_pressure")),
            safe_float(r.get("pressure_delta_3h")),
            safe_float(r.get("pressure_delta_6h")),
            safe_float(r.get("pressure_delta_12h")),
            safe_float(r.get("pressure_delta_24h")),
        )
        water_temp_val = safe_float(r.get("sea_surface_temperature"))
        water_s, water_desc = water_score(
            water_temp_val,
            safe_float(r.get("sst_delta_24h")),
            species,
        )
        precip_val = safe_float(r.get("precipitation"))
        turbidity = turbidity_index(wave_h_val, precip_val)
        light_s, light_desc = light_score(
            dt,
            safe_float(r.get("cloud_cover")),
            species,
            turbidity=turbidity,
        )
        rain_factor, rain_desc = rain_penalty(precip_val)
        hist_s, hist_conf, hist_desc = historical_score(
            carnet, spot["id"], species, technique, coef, dt
        )

        shom_current = shom_current_at(
            shom_ds, spot["lat"], spot["lon"], dt, tide_info_window, reference=shom_reference
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
            + spot[SPECIES_SPOT_KEY[species]] / 10 * w["spot"] * 10
        )

        # Le coefficient est déjà implicitement lié à la phase, mais on le
        # garde comme petit facteur distinct. Normalisation des poids :
        # la somme vaut > 1 dans la configuration ; on redivise.
        total_weight = (
            w["maree"] + 0.06 + w["courant"] + w["vent"] + w["houle"]
            + w["lumiere"] + w["eau"] + w["pression"] + w["historique"] + w["spot"]
        )
        # Moyenne pondérée des sous-scores, chacun déjà sur une échelle 0–10.
        # (Le score n'est multiplié par 10 qu'une seule fois, juste après,
        # pour obtenir l'échelle finale 0–100 : le multiplier deux fois
        # faisait saturer le clamp() et affichait quasi toujours 100/100,
        # quelle que soit la qualité réelle des conditions.)
        score = score / total_weight
        score = clamp(score, 0, 10) * 10
        # La pluie s'applique en facteur multiplicatif APRÈS la moyenne
        # pondérée : diluée parmi 8-9 autres facteurs, elle perdrait trop
        # d'impact même sous forte pluie, alors que c'est un critère
        # quasi rédhibitoire pour toi.
        score = round(score * rain_factor, 1)

        flags = [
            safe_float(r.get("wind_speed_10m")) is not None,
            safe_float(r.get("surface_pressure")) is not None,
            safe_float(r.get("sea_surface_temperature")) is not None,
            bool(extrema),
            safe_float(r.get("wave_height")) is not None,
            safe_float(r.get("precipitation")) is not None,
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
            "pluie": rain_desc,
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
            "rain_score": round(rain_factor * 10, 1),
            "wave_height_m": wave_h_val,
            "water_temp_c": water_temp_val,
            "turbidity_idx": round(turbidity, 1),
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
@st.cache_data(ttl=30 * 86400, show_spinner=False)
def fetch_maree_sites():
    """Liste des sites/ports disponibles sur api-maree.fr (endpoint public,
    sans clé). Mise en cache longue durée : cette liste ne change quasiment
    jamais.
    """
    try:
        r = requests.get("https://api-maree.fr/sites", headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.json().get("sites", [])
    except Exception as e:
        st.sidebar.warning(f"Liste des sites de marée indisponible : {e}")
        return []


def nearest_maree_site(lat, lon, sites):
    """Site le plus proche des coordonnées données, et sa distance en km."""
    best, best_dist = None, None
    for s in sites:
        try:
            d = haversine(lat, lon, float(s["latitude"]), float(s["longitude"]))
        except Exception:
            continue
        if best_dist is None or d < best_dist:
            best, best_dist = s, d
    return best, best_dist


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
            # L'API renvoie "time" au format "HH:MM" SEUL, sans date. Sans
            # correction, pd.to_datetime("HH:MM") complète silencieusement
            # avec la date d'exécution du script au lieu de la date réelle
            # de la marée, ce qui fait échouer l'encadrement PM/BM pour
            # tous les jours autres que celui du run ("Phase incomplète").
            # On reconstruit ici un horodatage complet jour + heure.
            full_extrema = []
            for e in extrema:
                e = dict(e)
                t = e.get("time")
                if t and "T" not in str(t) and len(str(t)) <= 5:
                    e["time"] = f"{d}T{t}:00"
                full_extrema.append(e)
            out[d] = {
                "max_coef": max(coefs) if coefs else 70,
                "extrema": full_extrema,
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

    # Le point analysé (spot connu ou secteur cliqué librement) se choisit
    # désormais sur la carte en haut de l'onglet "Indice & créneaux" — plus
    # de distinction "zone habituelle" / "vacances" à gérer ici.
    if "active_point" not in st.session_state:
        st.session_state["active_point"] = dict(SPOTS[0])
    spot = st.session_state["active_point"]

    st.divider()
    st.header("🌊 Courants SHOM")
    shom_reference = st.selectbox(
        "Référence temporelle de l'atlas", ["PM", "BM"], index=0,
        help="Le produit SHOM encode les échéances autour de la PM ou BM du port de référence de la grille."
    )
    shom_file = st.file_uploader(
        "Importer les données SHOM Courants 2D",
        type=None,
        help=(
            "Le plus simple : zippe tout le dossier téléchargé (ex. le "
            "dossier '558' pour Bretagne Sud) et importe le .zip — les "
            "fichiers de données SHOM n'ont pas d'extension (ex. "
            "'BRETAGNE_SUD_558'), d'où l'acceptation de tout type de "
            "fichier ici. TXT unique ou NetCDF (.nc) également acceptés."
        ),
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


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _load_shom_from_supabase_zones(lat, lon):
    """Charge automatiquement les zones SHOM (déjà envoyées une fois via
    upload_shom_zones.py) couvrant le point donné — pas d'upload manuel
    nécessaire. Retourne (shom_ds, zones_utilisées) ; zones_utilisées est
    une liste de noms pour affichage, vide si rien trouvé pour ce point.
    """
    try:
        zones = db.get_shom_zones_for_point(round(lat, 3), round(lon, 3))
    except Exception:
        return None, []
    if not zones:
        return None, []
    all_rows = []
    for z in zones:
        all_rows.extend(z.get("data") or [])
    if not all_rows:
        return None, []
    return {"kind": "txt", "data": pd.DataFrame(all_rows)}, [z["zone_name"] for z in zones]


# Chargement du fichier SHOM : upload manuel prioritaire s'il est fourni,
# sinon sélection automatique dans Supabase selon le spot analysé (table
# shom_zones, remplie une fois via upload_shom_zones.py).
shom_zone_names = []
if shom_file is not None:
    shom_ds, shom_error = _load_shom_with_shared_cache(shom_file, ZONE, shom_reference)
else:
    shom_ds, shom_zone_names = _load_shom_from_supabase_zones(spot["lat"], spot["lon"])
    shom_error = None

if shom_error:
    st.sidebar.error(f"Fichier SHOM illisible : {shom_error}")
elif shom_ds is not None and shom_zone_names:
    st.sidebar.success(f"✅ Courants SHOM (Supabase, zone {', '.join(shom_zone_names)})")
elif shom_ds is not None:
    st.sidebar.success("✅ Courants SHOM chargés (cache partagé) : utilisés dans le score horaire")
else:
    st.sidebar.caption(
        "Courants SHOM : aucune zone Supabase pour ce point — "
        "importer le paquet TXT/ZIP manuellement, ou lancer "
        "upload_shom_zones.py pour cette zone."
    )

# La météo est toujours interrogée au point exact du secteur analysé
# (spot connu ou point cliqué librement) — plus de cellule de référence
# fixe sur Le Croisic à gérer séparément.
lat_cible, lon_cible = spot["lat"], spot["lon"]

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

# Marées : sélection automatique du port api-maree.fr le plus proche du
# spot analysé (utile aussi bien au Croisic qu'en mode vacances, où aucun
# site n'est codé en dur).
maree_sites = fetch_maree_sites()
nearest_site, nearest_dist_km = nearest_maree_site(spot["lat"], spot["lon"], maree_sites)

dates = sorted(df["date"].dropna().unique())
start_date = dates[0]
end_date = dates[-1]

# Fallback si pas de clé : on continue à afficher météo/mer.
tides_dict = {}
if API_KEY_MAREE and nearest_site:
    tides_dict = fetch_tides(
        nearest_site["site_id"],
        start_date,
        end_date,
    )
    site_label = nearest_site.get("site_name") or nearest_site.get("name") or nearest_site["site_id"]
    if nearest_dist_km is not None and nearest_dist_km > 50:
        st.sidebar.warning(
            f"⚠️ Port de marée le plus proche : {site_label} "
            f"({nearest_dist_km:.0f} km) — assez loin, les marées locales "
            f"peuvent différer sensiblement de celles affichées."
        )
    else:
        st.sidebar.caption(
            f"🌊 Marées : {site_label}"
            + (f" ({nearest_dist_km:.0f} km)" if nearest_dist_km is not None else "")
        )
elif API_KEY_MAREE and not nearest_site:
    st.sidebar.warning("Impossible de déterminer le port de marée le plus proche.")

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
    st.markdown("### 🗺️ Zone analysée")
    st.caption("Clique un repère pour un spot connu, ou n'importe où ailleurs pour une zone personnalisée.")

    m_main = folium.Map(location=[spot["lat"], spot["lon"]], zoom_start=11, control_scale=True)
    for s in SPOTS:
        val = s["bar"] if species == "Bar" else s["daurade"]
        is_active = s["id"] == spot.get("id")
        color = "red" if is_active else ("green" if val >= 9 else ("orange" if val >= 8 else "blue"))
        folium.Marker(
            [s["lat"], s["lon"]],
            tooltip=f"{s['nom']} — {val}/10",
            icon=folium.Icon(color=color, icon="star" if is_active else "map-marker"),
        ).add_to(m_main)
    if str(spot.get("id", "")).startswith("point_"):
        folium.Marker(
            [spot["lat"], spot["lon"]],
            tooltip=spot["nom"],
            icon=folium.Icon(color="red", icon="map-pin"),
        ).add_to(m_main)

    main_map_data = st_folium(
        m_main, height=420, width="100%", key="main_point_map",
        returned_objects=["last_object_clicked_tooltip", "last_clicked"],
    )

    new_point = None
    if main_map_data and main_map_data.get("last_object_clicked_tooltip"):
        tt = main_map_data["last_object_clicked_tooltip"]
        for s in SPOTS:
            if tt.startswith(s["nom"]):
                new_point = dict(s)
                break
    elif main_map_data and main_map_data.get("last_clicked"):
        lat_c = main_map_data["last_clicked"]["lat"]
        lon_c = main_map_data["last_clicked"]["lng"]
        nearest_spot = min(SPOTS, key=lambda s: haversine(lat_c, lon_c, s["lat"], s["lon"]))
        if haversine(lat_c, lon_c, nearest_spot["lat"], nearest_spot["lon"]) < 0.5:
            new_point = dict(nearest_spot)
        else:
            new_point = {
                "id": ("point_" + f"{round(lat_c, 4)}_{round(lon_c, 4)}").replace(".", "_").replace("-", "m"),
                "nom": "Secteur personnalisé",
                "lat": lat_c, "lon": lon_c,
                "fond": "À renseigner", "orientation": 0, "exposition": "À renseigner",
                "bar": 7, "daurade": 7,
                "notes": "Secteur choisi sur la carte : caractéristiques locales à compléter.",
                "techniques_bar": "À adapter", "techniques_daurade": "À adapter",
            }

    if new_point and new_point.get("id") != spot.get("id"):
        st.session_state["active_point"] = new_point
        st.rerun()

    st.markdown(
        f'<div style="display:inline-block;background:rgba(128,128,128,0.15);'
        f'border-radius:20px;padding:6px 14px;font-size:13px;margin:4px 0">'
        f'📍 {spot["nom"]} · {spot["lat"]:.4f}, {spot["lon"]:.4f}</div>',
        unsafe_allow_html=True,
    )
    if API_KEY_MAREE and nearest_site:
        site_label = nearest_site.get("site_name") or nearest_site.get("name") or nearest_site["site_id"]
        dist_txt = f" ({nearest_dist_km:.0f} km)" if nearest_dist_km is not None else ""
        st.caption(f"🌊 Port de marée utilisé pour les calculs : {site_label}{dist_txt}")
    elif API_KEY_MAREE:
        st.caption("🌊 Port de marée : aucun port trouvé pour cette zone.")

    st.divider()

    if df_score.empty:
        st.warning("Pas assez de données pour calculer les créneaux.")
    else:
        st.subheader(
            f"{SPECIES[species]['emoji']} {species} — {technique} — {spot['nom']}"
        )

        st.markdown("### 📅 Vue par jour")
        # Ligne au score maximal de chaque jour (et non plus "premier élément
        # du groupe", qui prenait systématiquement l'heure 00:00 — d'où la
        # colonne "meilleure heure" toujours à zéro).
        best_idx = df_score.groupby("date")["score"].idxmax()
        daily = (
            df_score.loc[best_idx, ["date", "score", "confiance", "heure"]]
            .sort_values("date")  # tri chronologique (format ISO YYYY-MM-DD)
            .reset_index(drop=True)
        )
        # Samedi/dimanche (calculé avant reformatage de "date", conservé par
        # index pour la mise en valeur visuelle plus bas).
        is_weekend = pd.to_datetime(daily["date"]).dt.weekday >= 5

        # Pluie sur la JOURNÉE entière (distinct du badge de l'heure retenue,
        # qui ne reflète que le créneau précis choisi — un créneau sec peut
        # très bien tomber un jour globalement pluvieux ailleurs).
        if "precipitation" in df.columns:
            rain_by_day = (
                df.groupby("date")["precipitation"].sum().round(1)
                .rename("pluie_jour_mm")
            )
            daily = daily.merge(rain_by_day, left_on="date", right_index=True, how="left")
        else:
            daily["pluie_jour_mm"] = None

        # Indice heure par heure (00 à 23), une colonne par heure. En-têtes
        # raccourcis ("07" plutôt que "07:00") pour limiter la largeur totale.
        hour_pivot = df_score.pivot_table(index="date", columns="heure", values="score", aggfunc="first")
        hour_cols_full = sorted(hour_pivot.columns)
        hour_pivot = hour_pivot.reindex(columns=hour_cols_full)
        hour_cols = [h[:2] for h in hour_cols_full]
        hour_pivot.columns = hour_cols
        daily = daily.merge(hour_pivot, left_on="date", right_index=True, how="left")

        daily["date"] = pd.to_datetime(daily["date"]).dt.strftime("%d/%m")
        daily = daily.rename(columns={
            "date": "Date",
            "score": "Indice",
            "confiance": "Conf.%",
            "heure": "Heure",
            "pluie_jour_mm": "Pluie (mm)",
        })
        st.caption(
            "\"Pluie (mm)\" = cumul sur les 24h, même si le créneau retenu "
            "est sec (l'algorithme cherche la meilleure fenêtre, pas "
            "forcément toute la journée). Colonnes 00-23 : indice heure par "
            "heure (case vide = donnée indisponible). Week-ends surlignés."
        )

        def _daily_table_html(df_daily, hcols, weekend_mask):
            """Rendu HTML compact (pas st.dataframe) : le composant Streamlit
            standard impose un padding par colonne difficile à comprimer
            sous ~75-90px, ce qui gaspille beaucoup de largeur sur un
            tableau à 24 colonnes horaires. Un <table> HTML classique
            donne un contrôle total du padding/largeur par colonne.
            """
            widths = {"Date": "50px", "Indice": "38px", "Conf.%": "42px",
                      "Heure": "44px", "Pluie (mm)": "54px"}
            cols = ["Date", "Indice", "Conf.%", "Heure", "Pluie (mm)"] + hcols
            parts = [
                '<div style="overflow-x:auto">'
                '<table style="border-collapse:collapse;font-size:12px">'
                "<thead><tr>"
            ]
            for c in cols:
                w = widths.get(c, "30px")
                parts.append(
                    f'<th style="padding:3px 4px;text-align:center;white-space:nowrap;'
                    f'border-bottom:1px solid rgba(128,128,128,.4);width:{w};min-width:{w}">{c}</th>'
                )
            parts.append("</tr></thead><tbody>")
            for idx, row in df_daily.iterrows():
                weekend = bool(weekend_mask.loc[idx])
                date_css = "font-weight:700;background-color:rgba(66,133,244,.18)" if weekend else ""
                parts.append("<tr>")
                parts.append(f'<td style="padding:3px 4px;white-space:nowrap;{date_css}">{row["Date"]}</td>')
                parts.append(
                    f'<td style="padding:3px 4px;text-align:center;{score_css_100(row["Indice"])}">'
                    f'{row["Indice"]:.0f}</td>'
                )
                parts.append(f'<td style="padding:3px 4px;text-align:center">{row["Conf.%"]:.0f}</td>')
                parts.append(f'<td style="padding:3px 4px;text-align:center;white-space:nowrap">{row["Heure"]}</td>')
                pv = row["Pluie (mm)"]
                if pd.isna(pv):
                    parts.append('<td style="padding:3px 4px;text-align:center">—</td>')
                else:
                    parts.append(
                        f'<td style="padding:3px 4px;text-align:center;{rain_mm_css(pv)}">{pv:.1f}</td>'
                    )
                for h in hcols:
                    v = row[h]
                    if pd.isna(v):
                        parts.append('<td style="padding:3px 2px;text-align:center;color:rgba(128,128,128,.6)">—</td>')
                    else:
                        parts.append(
                            f'<td style="padding:3px 2px;text-align:center;{score_css_100(v)}">{v:.0f}</td>'
                        )
                parts.append("</tr>")
            parts.append("</tbody></table></div>")
            return "".join(parts)

        st.markdown(_daily_table_html(daily, hour_cols, is_weekend), unsafe_allow_html=True)

        st.markdown("### 🔍 Analyse détaillée")
        st.caption("Clique un jour pour voir le détail")

        unique_dates = sorted(df_score["date"].unique())
        best_per_day = df_score.loc[df_score.groupby("date")["score"].idxmax()].set_index("date")

        if "detail_date" not in st.session_state or st.session_state["detail_date"] not in unique_dates:
            st.session_state["detail_date"] = unique_dates[0]

        def _score_dot(score):
            if score is None:
                return "⚪"
            if score > 75:
                return "🟢"
            if score > 50:
                return "🟠"
            return "🔴"

        n_cols = 7
        for start in range(0, len(unique_dates), n_cols):
            row_dates = unique_dates[start:start + n_cols]
            cols = st.columns(n_cols)
            for i, d in enumerate(row_dates):
                score_d = best_per_day.loc[d, "score"] if d in best_per_day.index else None
                label_date = pd.to_datetime(d).strftime("%d/%m")
                btn_label = f"{_score_dot(score_d)} {label_date}"
                is_selected = d == st.session_state["detail_date"]
                with cols[i]:
                    if st.button(
                        btn_label,
                        key=f"day_btn_{d}",
                        use_container_width=True,
                        type="primary" if is_selected else "secondary",
                    ):
                        st.session_state["detail_date"] = d
                        st.rerun()

        chosen_date = st.session_state["detail_date"]
        day = df_score[df_score["date"] == chosen_date].copy()

        # Seuils identiques à la pastille des boutons ci-dessus :
        # 🟢 ≥ 65, 🟠 40-65, 🔴 < 40.
        def render_badges(items):
            html = '<div style="display:flex;flex-wrap:wrap;gap:8px;margin:8px 0 16px">'
            for label, score10, detail in items:
                if score10 is None:
                    bg = "background:#e0e0e0"
                else:
                    r, g, b = score_rgb_100(score10 * 10)
                    bg = f"background:rgb({r},{g},{b})"
                score_txt = f"{score10:.1f}/10" if score10 is not None else "—"
                html += (
                    f'<div style="{bg};color:#ffffff;border-radius:8px;'
                    f'padding:8px 12px;min-width:130px;flex:1">'
                    f'<div style="font-size:11px;opacity:.85">{label}</div>'
                    f'<div style="font-size:15px;font-weight:600">{score_txt}</div>'
                    f'<div style="font-size:11px">{detail}</div>'
                    f'</div>'
                )
            html += '</div>'
            st.markdown(html, unsafe_allow_html=True)

        if not day.empty:
            day_sorted = day.sort_values("heure").reset_index(drop=True)
            best_idx_in_day = int(day_sorted["score"].idxmax())

            selected_heure = st.selectbox(
                "Heure du créneau à détailler",
                day_sorted["heure"].tolist(),
                index=best_idx_in_day,
                key=f"detail_heure_{chosen_date}",
                help="Pré-sélectionné sur le meilleur moment de la journée ; choisis une autre heure pour comparer.",
            )
            best_day = day_sorted[day_sorted["heure"] == selected_heure].iloc[0]
            is_best = selected_heure == day_sorted.loc[best_idx_in_day, "heure"]

            st.markdown(
                f"#### {chosen_date} · {best_day['heure']} "
                f"{'(meilleur moment)' if is_best else ''}"
            )

            c1, c2 = st.columns(2)
            c1.metric("Indice", f"{best_day['score']:.0f}/100")
            c2.metric("Confiance", f"{best_day['confiance']}%")

            factors = [
                ("Marée", best_day["tide_score"], best_day["phase_desc"]),
                ("Courant", best_day["current_score"], best_day["courant"]),
                ("Vent", best_day["wind_score"], best_day["vent"]),
                ("Houle", best_day["wave_score"], best_day["houle"]),
                ("Pression", best_day["pressure_score"], best_day["pression"]),
                ("Eau", best_day["water_score"], best_day["eau"]),
                ("Lumière", best_day["light_score"], best_day["lumiere"]),
                ("Pluie", best_day["rain_score"], best_day["pluie"]),
            ]
            render_badges(factors + [("Historique", None, best_day["historique"])])

            if "precipitation" in df.columns:
                pluie_jour = df.loc[df["date"] == chosen_date, "precipitation"].sum()
                if pluie_jour > 2 and best_day["rain_score"] >= 7:
                    st.warning(
                        f"⚠️ Le créneau retenu est sec, mais il pleut ailleurs "
                        f"ce jour-là (cumul {pluie_jour:.1f} mm sur 24h). "
                        f"Vérifie les horaires avant de partir."
                    )

            # --- Résumé, recommandation et alternative ---
            st.markdown("#### 📌 Résumé du créneau")
            factors_sorted = sorted(factors, key=lambda f: f[1])
            faibles = [f for f in factors_sorted if f[1] <= 5][:2]
            forts = [f for f in factors_sorted[::-1] if f[1] >= 7][:2]
            if forts:
                st.write(
                    "✅ Points forts : "
                    + ", ".join(f"{n} ({s:.1f}/10)" for n, s, _ in forts)
                )
            if faibles:
                st.write(
                    "⚠️ Points de vigilance : "
                    + ", ".join(f"{n} ({s:.1f}/10)" for n, s, _ in faibles)
                )
            if not forts and not faibles:
                st.write("Conditions globalement moyennes, sans facteur particulièrement favorable ou défavorable.")

            st.markdown("#### 🎯 Technique recommandée")
            reco_principale = recommendation_for(species, technique, best_day["score"], best_day, spot)
            st.info(f"**{technique}** — {reco_principale}")

            st.markdown("#### 🔄 Alternative si ça ne mord pas")
            # Alternative choisie pour être réellement à l'opposé de la
            # technique principale (profondeur/canal sensoriel pour le bar,
            # sélectivité de l'appât pour la daurade) plutôt qu'une simple
            # variante voisine.
            ALT_TECHNIQUE = {
                "Bar": {
                    "Surface": "Leurre souple",       # vue/surface -> vibration/fond
                    "Leurre souple": "Surface",         # fond/vibration -> vue/surface
                    "Métal": "Jerkbait / minnow",       # rapide/flash -> lent/imitatif
                    "Jerkbait / minnow": "Métal",       # lent/imitatif -> rapide/flash
                },
                "Daurade royale": {
                    "Crabe au posé": "Ver",             # très sélectif -> universel
                    "Ver": "Crabe au posé",             # universel -> très sélectif
                    "Couteau / coquillage": "Crabe au posé",
                },
            }
            default_alt = {"Bar": "Leurre souple", "Daurade royale": "Crabe au posé"}
            alt_technique = ALT_TECHNIQUE.get(species, {}).get(technique)
            if not alt_technique or alt_technique == technique:
                alt_technique = default_alt.get(species, technique)
            reco_alt = recommendation_for(species, alt_technique, best_day["score"], best_day, spot)
            st.caption(f"**{alt_technique}** — {reco_alt}")

            st.markdown("**🌊 Pleines mers / basses mers du jour**")
            extrema_day = tides_dict.get(chosen_date, {}).get("extrema", [])
            if extrema_day:
                rows_tide = []
                for e in sorted(extrema_day, key=lambda x: str(x.get("time", ""))):
                    t = str(e.get("time", ""))
                    heure = t.split("T")[-1][:5] if "T" in t else t
                    rows_tide.append({
                        "Type": "Pleine mer" if e.get("type") == "PM" else "Basse mer",
                        "Heure": heure,
                        "Hauteur (m)": e.get("height"),
                        "Coefficient": e.get("coef", "—"),
                    })
                st.dataframe(pd.DataFrame(rows_tide), use_container_width=True, hide_index=True)
            else:
                st.caption("Aucune donnée de marée disponible pour ce jour.")

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
    st.caption("Pour changer de secteur actif, utilise la carte en haut de l'onglet \"Indice & créneaux\".")

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
        is_active = s["id"] == spot.get("id")
        color = "red" if is_active else ("green" if val >= 9 else ("orange" if val >= 8 else "blue"))
        icon_name = "star" if is_active else "map-marker"

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
            icon=folium.Icon(color=color, icon=icon_name),
        ).add_to(m)

    st_folium(
        m, height=600, width="100%", key="spots_map_readonly",
        returned_objects=[],
    )

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

        # --- Visualisation dynamique : flèches de courant heure par heure ---
        st.markdown("### 🧭 Visualisation dynamique du courant")
        if not (isinstance(shom_ds, dict) and shom_ds.get("kind") == "txt"):
            st.info("Cette visualisation n'est disponible que pour le format TXT/ZIP (pas encore le NetCDF).")
        else:
            available_dates = sorted(tides_dict.keys()) if tides_dict else []
            if not available_dates:
                st.info("Pas de données de marée disponibles pour situer les échéances du jour.")
            else:
                viz_date = st.selectbox("Jour à visualiser", available_dates, key="shom_viz_date")
                radius_km = st.slider("Rayon autour du spot (km)", 2, 40, 15, key="shom_viz_radius")

                with st.spinner("Calcul du champ de courant heure par heure..."):
                    hours = list(range(24))
                    hourly_fields = {}
                    last_err = None
                    for h in hours:
                        field, err = shom_field_at_hour(
                            shom_ds, tides_dict, viz_date, h, shom_reference,
                            spot["lat"], spot["lon"], radius_km=radius_km,
                        )
                        hourly_fields[h] = field
                        if err:
                            last_err = err

                if all(f is None for f in hourly_fields.values()):
                    st.warning(
                        "Aucune heure exploitable pour ce jour/rayon. "
                        + (f"Détail : {last_err}" if last_err else "")
                    )
                else:
                    n_ok = sum(1 for f in hourly_fields.values() if f is not None)
                    st.caption(
                        f"{n_ok}/24 heures avec un champ de courant calculable dans un rayon de {radius_km} km. "
                        "Clique ▶️ Lecture pour l'animation (défile 1x sur la journée), "
                        "ou utilise le curseur pour naviguer heure par heure."
                    )
                    fig = build_current_arrows_figure(hourly_fields, hours, spot["lat"], spot["lon"])
                    st.plotly_chart(fig, use_container_width=True)
                    st.caption(
                        "⚠️ Limite connue : le bouton Lecture de Plotly joue la séquence une fois "
                        "puis s'arrête sur la dernière heure — reclique pour rejouer. Une boucle "
                        "continue nécessiterait un composant JS dédié, hors de portée simple ici."
                    )

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
        session_spot_label = st.text_input(
            "Spot",
            value=spot["nom"],
            help="Pré-rempli avec le secteur actif (choisi sur la carte). Modifiable si besoin.",
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
        chosen = {"id": spot["id"], "nom": session_spot_label}
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

    with st.expander("🔧 Diagnostic marées (brut API)"):
        st.caption(
            "Sert à vérifier le format exact renvoyé par api-maree.fr — "
            "utile si les phases de marée affichent 'Phase incomplète' de "
            "façon inattendue."
        )
        st.write("Jours reçus :", sorted(tides_dict.keys()) if tides_dict else "Aucun")
        if tides_dict:
            first_day = sorted(tides_dict.keys())[0]
            st.write(f"Exemple — {first_day} :")
            st.json(tides_dict[first_day])
        else:
            st.warning("tides_dict est vide : la clé/le site ne renvoie rien exploitable.")

    with st.expander("🔧 Diagnostic pluie / nébulosité (données brutes Open-Meteo)"):
        st.caption(
            "Sert à vérifier les valeurs de précipitations et de couverture "
            "nuageuse réellement reçues, si l'indice pluie semble ne pas "
            "refléter les prévisions."
        )
        if not df_score.empty and "date" in df.columns:
            diag = (
                df[["date", "precipitation", "cloud_cover"]]
                .groupby("date")
                .agg(
                    precipitation_max_mm_h=("precipitation", "max"),
                    precipitation_totale_mm=("precipitation", "sum"),
                    nuages_moyen_pct=("cloud_cover", "mean"),
                )
                .round(2)
                .reset_index()
            )
            st.dataframe(diag, use_container_width=True, hide_index=True)
            st.caption(
                "Rappel des seuils : pluie ≤0.05 mm/h = temps sec (score inchangé) · "
                "≤0.5 = bruine (×0.9) · ≤2 = pluie légère (×0.55) · "
                "≤5 = modérée (×0.3) · au-delà = forte (×0.15)."
            )
        else:
            st.warning("Pas de données météo chargées pour l'instant.")

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
