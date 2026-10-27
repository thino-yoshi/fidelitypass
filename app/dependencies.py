from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
import os

security = HTTPBearer()


def _resolve_user_type(meta: dict) -> str:
    """
    Détermine le type de compte depuis user_metadata.
    Règle : site = marchand (clé `role`), app = client (clé `user_type`).
    On lit les deux clés pour être robuste quel que soit l'endroit de création.
    """
    ut = (meta.get("user_type") or "").strip()
    if ut in ("merchant", "client"):
        return ut
    role = (meta.get("role") or "").strip()
    if role == "merchant":
        return "merchant"
    return "client"


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Vérifie le token Bearer et retourne un payload normalisé :
      { "sub": "<uuid>", "user_type": "<client|merchant>", "email": "<email>" }

    Stratégie (ordre de priorité) :
      1. Décodage local avec SUPABASE_JWT_SECRET (HS256) — tokens Supabase
      2. Décodage local avec SECRET_KEY (HS256) — tokens backend (email/Google mobile)
      3. Supabase Auth API — fallback réseau
    """
    from app.database import supabase, SUPABASE_JWT_SECRET, SECRET_KEY

    token = credentials.credentials

    # ── 1. Token Supabase (SUPABASE_JWT_SECRET) ─────────────────────────────────
    jwt_secret = SUPABASE_JWT_SECRET or os.getenv("SUPABASE_JWT_SECRET")
    if jwt_secret:
        try:
            payload = jwt.decode(
                token,
                jwt_secret,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
            user_metadata = payload.get("user_metadata") or {}
            user_type = _resolve_user_type(user_metadata)
            sub = payload.get("sub")
            if sub:
                return {
                    "sub":       sub,
                    "user_type": user_type,
                    "email":     payload.get("email") or "",
                }
        except JWTError:
            pass

    # ── 2. Token backend (SECRET_KEY) — email/password ou Google mobile ─────────
    secret_key = SECRET_KEY or os.getenv("SECRET_KEY")
    if secret_key:
        try:
            payload = jwt.decode(token, secret_key, algorithms=["HS256"])
            sub = payload.get("sub")
            if sub:
                return {
                    "sub":       sub,
                    "user_type": payload.get("user_type", "client"),
                    "email":     payload.get("email", ""),
                }
        except JWTError:
            pass

    # ── 3. Supabase Auth API (fallback réseau) ──────────────────────────────────
    try:
        response = supabase.auth.get_user(token)
        if response and response.user:
            user = response.user
            user_metadata = user.user_metadata or {}
            user_type = _resolve_user_type(user_metadata)
            return {
                "sub":       user.id,
                "user_type": user_type,
                "email":     user.email or "",
            }
    except Exception:
        pass

    raise HTTPException(status_code=401, detail="Token invalide ou expiré")
