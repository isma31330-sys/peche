"""
prefetch_meteo_cache.py
========================
Pré-remplit le cache météo/marine partagé Supabase (table cache_meteo) pour
Le Croisic et les 10 spots préconfigurés, DEPUIS une machine différente de
Streamlit Cloud (ex. GitHub Actions). Objectif : que l'appli ne rappelle
quasiment jamais Open-Meteo en direct pendant une visite, ce qui évite les
429 causés par l'IP partagée de Streamlit Cloud (limite appliquée par
adresse IP, pas par application — documenté sur le dépôt GitHub d'Open-Meteo).

Utilise EXACTEMENT le même format de clé de cache et la même durée de vie
que l'appli (voir _fetch_weather_cached / _fetch_marine_cached dans
appV6_2.py), pour que l'appli retrouve directement ces entrées.

Installation :
    pip install supabase requests

Utilisation :
    python prefetch_meteo_cache.py --url "https://xxxx.supabase.co" --key "..." --email "..." --password "..."

Prévu pour être lancé par un workflow programmé (voir
.github/workflows/prefetch_meteo.yml) toutes les 4h — la durée de vie du
cache est de 6h, donc une marge confortable même si une exécution échoue.
"""

import argparse
import sys
import time

import requests

try:
    from supabase import create_client
except ImportError:
    print("Il manque la librairie 'supabase'. Installe-la avec :")
    print("    pip install supabase")
    sys.exit(1)


HEADERS = {"User-Agent": "IndicePecheV6-Prefetch/1.0"}
ZONE = "le_croisic"
TTL_SECONDS = 6 * 3600  # doit correspondre à la durée de vie utilisée par l'appli

# Mêmes coordonnées que dans l'appli (CENTER + SPOTS de appV6_2.py).
CENTER = {"lat": 47.2931, "lon": -2.5204, "nom": "Le Croisic"}
SPOTS = [
    {"nom": "Pointe du Croisic / Côte sauvage", "lat": 47.2848, "lon": -2.5450},
    {"nom": "Port Lin / Castouillet", "lat": 47.2745, "lon": -2.5235},
    {"nom": "Pointe de Penchâteau — La Baule", "lat": 47.2560, "lon": -2.4260},
    {"nom": "La Govelle / rochers", "lat": 47.2630, "lon": -2.4340},
    {"nom": "La Turballe — digue / musoir", "lat": 47.3465, "lon": -2.5120},
    {"nom": "La Turballe — secteur port / Port Creux", "lat": 47.3485, "lon": -2.5070},
    {"nom": "Piriac — Pointe de Castelli", "lat": 47.3790, "lon": -2.5445},
    {"nom": "Piriac — Les Grillades", "lat": 47.3815, "lon": -2.5500},
    {"nom": "Mesquer — Kercabellec", "lat": 47.3970, "lon": -2.4630},
    {"nom": "Pen-Bron — entrée du Traict", "lat": 47.3420, "lon": -2.5100},
]


def _open_meteo_get(url, label="Open-Meteo"):
    """GET simple avec retries — plus léger que la version app, ce script
    tourne en tâche de fond sans interface à alimenter."""
    last_error = None
    for attempt in range(4):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if r.status_code == 429:
                wait = 5 * (attempt + 1)
                print(f"    429 sur {label}, attente {wait}s...")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            last_error = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{label} : échec après plusieurs tentatives ({last_error})")


def fetch_weather_records(lat, lon):
    variables = ",".join([
        "temperature_2m", "surface_pressure", "wind_speed_10m", "wind_direction_10m",
        "cloud_cover", "precipitation",
    ])
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}&hourly={variables}"
        "&forecast_days=14&timezone=Europe%2FParis"
    )
    data = _open_meteo_get(url, "Météo")
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    records = []
    for i, t in enumerate(times):
        row = {"time": t}
        for var in variables.split(","):
            vals = hourly.get(var, [])
            row[var] = vals[i] if i < len(vals) else None
        records.append(row)
    return records


def fetch_marine_records(lat, lon):
    variables = ",".join([
        "wave_height", "wave_direction", "wave_period",
        "sea_surface_temperature", "ocean_current_velocity", "ocean_current_direction",
    ])
    url = (
        "https://marine-api.open-meteo.com/v1/marine"
        f"?latitude={lat}&longitude={lon}&hourly={variables}"
        # Limite dure de l'API marine : 8 jours max (contre 16 pour la météo).
        "&forecast_days=8&timezone=Europe%2FParis&cell_selection=sea"
    )
    data = _open_meteo_get(url, "Marine")
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    records = []
    for i, t in enumerate(times):
        row = {"time": t}
        for var in variables.split(","):
            vals = hourly.get(var, [])
            row[var] = vals[i] if i < len(vals) else None
        records.append(row)
    return records


def store_cache(client, zone_key, type_, records):
    from datetime import datetime, timedelta, timezone as tz
    expires_at = (datetime.now(tz.utc) + timedelta(seconds=TTL_SECONDS)).isoformat()
    client.table("cache_meteo").insert(
        {"zone": zone_key, "type": type_, "data": records, "expires_at": expires_at}
    ).execute()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    client = create_client(args.url, args.key)
    print("Connexion à Supabase...")
    auth_res = client.auth.sign_in_with_password({"email": args.email, "password": args.password})
    if not auth_res.session:
        print("Échec de connexion — vérifie l'email/mot de passe.")
        sys.exit(1)
    client.auth.set_session(auth_res.session.access_token, auth_res.session.refresh_token)
    print("Connecté.\n")

    points = [CENTER] + SPOTS
    ok, fail = 0, 0
    for p in points:
        lat, lon = round(p["lat"], 2), round(p["lon"], 2)
        zone_key = f"{ZONE}_{lat}_{lon}"
        try:
            weather = fetch_weather_records(p["lat"], p["lon"])
            store_cache(client, zone_key, "meteo", weather)
            print(f"  [ok] météo  — {p['nom']} ({len(weather)} points horaires)")
            ok += 1
        except Exception as e:
            print(f"  [erreur] météo  — {p['nom']} : {e}")
            fail += 1

        try:
            marine = fetch_marine_records(p["lat"], p["lon"])
            store_cache(client, zone_key, "marine", marine)
            print(f"  [ok] marine — {p['nom']} ({len(marine)} points horaires)")
            ok += 1
        except Exception as e:
            print(f"  [erreur] marine — {p['nom']} : {e}")
            fail += 1

        time.sleep(1)  # limite le débit vers Open-Meteo

    print(f"\nTerminé : {ok} entrées mises en cache, {fail} échecs.")


if __name__ == "__main__":
    main()
