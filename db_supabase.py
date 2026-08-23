# ============================================================
# db_supabase.py
# Couche d'accès aux données Supabase pour l'app Indice Pêche V6.2
#
# Remplace : charger_carnet() / sauvegarder_carnet() / CARNET_FILE
# de appV6_1.py, ainsi que le stockage local du fichier SHOM.
#
# Installation :
#   pip install supabase
#
# Config (Streamlit Cloud > Settings > Secrets, ou .streamlit/secrets.toml) :
#   SUPABASE_URL = "https://xxxx.supabase.co"
#   SUPABASE_ANON_KEY = "eyJ..."
# ============================================================

import os
import json
import hashlib
from datetime import datetime, timedelta, timezone

import streamlit as st
from supabase import create_client, Client


# -----------------------------
# Connexion
# -----------------------------
@st.cache_resource(show_spinner=False)
def get_client() -> Client:
    url = st.secrets.get("SUPABASE_URL", os.getenv("SUPABASE_URL", ""))
    key = st.secrets.get("SUPABASE_ANON_KEY", os.getenv("SUPABASE_ANON_KEY", ""))
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL / SUPABASE_ANON_KEY manquants dans st.secrets."
        )
    return create_client(url, key)


# -----------------------------
# Authentification
# -----------------------------
def sign_in(email: str, password: str):
    """Connecte l'utilisateur et stocke la session dans st.session_state."""
    client = get_client()
    res = client.auth.sign_in_with_password({"email": email, "password": password})
    if res.session:
        st.session_state["sb_session"] = res.session
        st.session_state["sb_user"] = res.user
        # Le client garde le token en mémoire pour les requêtes RLS suivantes.
        client.auth.set_session(res.session.access_token, res.session.refresh_token)
    return res


def sign_up(email: str, password: str):
    client = get_client()
    return client.auth.sign_up({"email": email, "password": password})


def sign_out():
    client = get_client()
    try:
        client.auth.sign_out()
    finally:
        st.session_state.pop("sb_session", None)
        st.session_state.pop("sb_user", None)


def current_user_id():
    user = st.session_state.get("sb_user")
    return user.id if user else None


def is_authenticated() -> bool:
    return current_user_id() is not None


def require_login_ui():
    """Bloc de connexion à afficher tant que l'utilisateur n'est pas authentifié.
    Retourne True si l'utilisateur est connecté (et l'app peut continuer),
    False sinon (dans ce cas, appeler st.stop() juste après dans l'app).
    """
    if is_authenticated():
        return True

    st.title("🎣 Indice Pêche — Connexion")
    tab_login, tab_signup = st.tabs(["Connexion", "Créer un compte"])

    with tab_login:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Mot de passe", type="password")
            submitted = st.form_submit_button("Se connecter")
            if submitted:
                try:
                    sign_in(email, password)
                    st.rerun()
                except Exception as e:
                    st.error(f"Connexion impossible : {e}")

    with tab_signup:
        with st.form("signup_form"):
            email_s = st.text_input("Email", key="signup_email")
            password_s = st.text_input("Mot de passe", type="password", key="signup_pwd")
            submitted_s = st.form_submit_button("Créer le compte")
            if submitted_s:
                try:
                    sign_up(email_s, password_s)
                    st.success(
                        "Compte créé. Selon la config Supabase, une confirmation "
                        "par email peut être nécessaire avant la première connexion."
                    )
                except Exception as e:
                    st.error(f"Création impossible : {e}")

    return False


# -----------------------------
# Sessions / Captures (carnet)
# -----------------------------
def save_session(session_dict: dict, captures: list[dict] | None = None) -> str:
    """Insère une session, puis ses captures éventuelles.
    session_dict attend les clés : date, heure_debut, heure_fin, spot_id,
    spot_nom, espece_ciblee, technique, conditions (dict), nb_poissons,
    touches, decroches, commentaire.
    captures est une liste de dicts : espece, heure, taille_cm, poids_kg,
    leurre_appat, technique, photo_url, observations.
    Retourne l'id de la session créée.
    """
    client = get_client()
    user_id = current_user_id()
    if not user_id:
        raise RuntimeError("Utilisateur non authentifié.")

    row = {**session_dict, "user_id": user_id}
    res = client.table("sessions").insert(row).execute()
    session_id = res.data[0]["id"]

    if captures:
        rows = [
            {**c, "session_id": session_id, "user_id": user_id}
            for c in captures
        ]
        client.table("captures").insert(rows).execute()

    return session_id


def load_sessions() -> list[dict]:
    client = get_client()
    user_id = current_user_id()
    if not user_id:
        return []
    res = (
        client.table("sessions")
        .select("*")
        .eq("user_id", user_id)
        .order("date", desc=True)
        .execute()
    )
    return res.data or []


def load_captures(session_id: str | None = None) -> list[dict]:
    client = get_client()
    user_id = current_user_id()
    if not user_id:
        return []
    q = client.table("captures").select("*").eq("user_id", user_id)
    if session_id:
        q = q.eq("session_id", session_id)
    res = q.execute()
    return res.data or []


def delete_session(session_id: str):
    """Supprime une session (les captures liées partent en cascade — ON DELETE CASCADE)."""
    client = get_client()
    client.table("sessions").delete().eq("id", session_id).execute()


def export_carnet_json() -> str:
    """Export complet (sessions + captures) au format JSON, pour la sauvegarde locale."""
    sessions = load_sessions()
    captures = load_captures()
    return json.dumps(
        {"sessions": sessions, "captures": captures},
        ensure_ascii=False,
        indent=2,
        default=str,
    )


# -----------------------------
# Photos (Supabase Storage)
# -----------------------------
def upload_photo(file_bytes: bytes, filename: str, content_type: str = "image/jpeg") -> str:
    """Upload une photo dans le bucket 'peche', sous peche/<user_id>/<filename>.
    Retourne le chemin de l'objet (à stocker dans captures.photo_url).
    """
    client = get_client()
    user_id = current_user_id()
    if not user_id:
        raise RuntimeError("Utilisateur non authentifié.")

    path = f"{user_id}/{filename}"
    client.storage.from_("peche").upload(
        path, file_bytes, {"content-type": content_type, "upsert": "true"}
    )
    return path


def get_photo_url(path: str, expires_in: int = 3600) -> str:
    """Bucket privé : on génère une URL signée temporaire pour l'affichage."""
    client = get_client()
    res = client.storage.from_("peche").create_signed_url(path, expires_in)
    return res.get("signedURL") or res.get("signed_url", "")


# -----------------------------
# Spots personnels
# -----------------------------
def load_spots() -> list[dict]:
    client = get_client()
    user_id = current_user_id()
    if not user_id:
        return []
    res = client.table("spots").select("*").eq("user_id", user_id).execute()
    return res.data or []


def save_spot(spot_dict: dict) -> str:
    client = get_client()
    user_id = current_user_id()
    row = {**spot_dict, "user_id": user_id}
    res = client.table("spots").insert(row).execute()
    return res.data[0]["id"]


# -----------------------------
# Cache SHOM (partagé entre utilisateurs authentifiés)
# -----------------------------
def _checksum(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def get_cached_shom(zone: str, source_checksum: str) -> dict | None:
    """Retourne les données SHOM déjà prétraitées si le fichier source
    (identifié par son checksum) a déjà été chargé une fois.
    """
    client = get_client()
    res = (
        client.table("cache_shom")
        .select("*")
        .eq("zone", zone)
        .eq("source_checksum", source_checksum)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if res.data:
        return res.data[0]["data"]
    return None


def store_shom_cache(zone: str, data: dict, source_checksum: str, reference: str = "PM", version_label: str = ""):
    client = get_client()
    client.table("cache_shom").insert(
        {
            "zone": zone,
            "data": data,
            "source_checksum": source_checksum,
            "reference": reference,
            "version_label": version_label,
        }
    ).execute()


def load_shom_dataset_cached(uploaded_file, zone: str, reference: str, preprocess_fn):
    """Wrapper : évite de retraiter le ZIP/TXT SHOM s'il a déjà été vu.
    preprocess_fn(uploaded_file) doit retourner un objet JSON-sérialisable
    (par exemple le résultat de load_shom_dataset(...) converti en dict/records).
    """
    if uploaded_file is None:
        return None

    raw = uploaded_file.getvalue()
    checksum = _checksum(raw)

    cached = get_cached_shom(zone, checksum)
    if cached is not None:
        return cached

    processed = preprocess_fn(uploaded_file)
    store_shom_cache(zone, processed, checksum, reference)
    return processed


# -----------------------------
# Cache météo / marine / marées (partagé)
# -----------------------------
def get_cached_meteo(zone: str, type_: str) -> dict | None:
    client = get_client()
    now_iso = datetime.now(timezone.utc).isoformat()
    res = (
        client.table("cache_meteo")
        .select("*")
        .eq("zone", zone)
        .eq("type", type_)
        .gt("expires_at", now_iso)
        .order("fetched_at", desc=True)
        .limit(1)
        .execute()
    )
    if res.data:
        return res.data[0]["data"]
    return None


def store_meteo_cache(zone: str, type_: str, data: dict, ttl_seconds: int = 21600):
    client = get_client()
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()
    client.table("cache_meteo").insert(
        {"zone": zone, "type": type_, "data": data, "expires_at": expires_at}
    ).execute()


def fetch_with_cache(zone: str, type_: str, fetch_fn, ttl_seconds: int = 21600):
    """Wrapper générique : sert le cache Supabase s'il est encore valide,
    sinon appelle fetch_fn() (ex: fetch_weather / fetch_marine / fetch_tides)
    et met à jour le cache. fetch_fn doit retourner un objet JSON-sérialisable
    (convertir un DataFrame avec df.to_dict(orient="records") avant appel).
    """
    cached = get_cached_meteo(zone, type_)
    if cached is not None:
        return cached

    fresh = fetch_fn()
    store_meteo_cache(zone, type_, fresh, ttl_seconds)
    return fresh
