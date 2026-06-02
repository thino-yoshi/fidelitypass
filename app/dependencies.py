from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
import os

security = HTTPBearer()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Vérifie le token Bearer et retourne un payload normalisé :
      { "sub": "<uuid>", "user_type": "<client|merchant>", "email": "<email>" }

    Ordre de vérification :
      1. Supabase Auth API — supabase.auth.get_user(token)
         Fonctionne avec tous les algos (ES256 P-256 actuel, HS256 legacy, futurs)
         → tokens émis par Supabase Auth (app Flutter migrée + qarta.be)
      2. Legacy JWT HS256 — fallback sur SECRET_KEY
         → anciens tokens custom pendant la période de migration Flutter
    """
    from app.database import supabase, SECRET_KEY  # import local pour éviter les imports circulaires

    token = credentials.credentials

    # ── 1. Supabase Auth API (ES256 / tout algorithme) ─────────────────────────
    try:
        response = supabase.auth.get_user(jwt=token)
        if response and response.user:
            user = response.user
            user_metadata = user.user_metadata or {}
            user_type = (
                user_metadata.get("user_type")
                or "client"
            )
            return {
                "sub":       user.id,
                "user_type": user_type,
                "email":     user.email or "",
            }
    except Exception:
        pass  # token pas Supabase ou invalide → essaie le fallback

    # ── 2. Legacy JWT HS256 (fallback pendant la migration) ────────────────────
    secret_key = SECRET_KEY or os.getenv("SECRET_KEY")
    if secret_key:
        try:
            payload = jwt.decode(token, secret_key, algorithms=["HS256"])
            return payload  # payload déjà normalisé (sub, user_type)
        except JWTError:
            pass

    raise HTTPException(status_code=401, detail="Token invalide ou expiré")
