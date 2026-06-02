from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
import os

security = HTTPBearer()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Vérifie le token Bearer Supabase et retourne un payload normalisé :
      { "sub": "<uuid>", "user_type": "<client|merchant>", "email": "<email>" }

    Stratégie (ordre de priorité) :
      1. Décodage local JWT avec SUPABASE_JWT_SECRET (HS256) — rapide, pas de réseau
      2. Supabase Auth API — fallback si le secret n'est pas dispo
    """
    from app.database import supabase, SUPABASE_JWT_SECRET

    token = credentials.credentials

    # ── 1. Décodage local (SUPABASE_JWT_SECRET, HS256) ─────────────────────────
    #   Les JWTs Supabase contiennent user_metadata directement dans le payload.
    #   Beaucoup plus rapide que l'appel réseau à get_user().
    jwt_secret = SUPABASE_JWT_SECRET or os.getenv("SUPABASE_JWT_SECRET")
    if jwt_secret:
        try:
            payload = jwt.decode(
                token,
                jwt_secret,
                algorithms=["HS256"],
                options={"verify_aud": False},  # audience = "authenticated" côté Supabase
            )
            user_metadata = payload.get("user_metadata") or {}
            user_type = user_metadata.get("user_type") or "client"
            sub = payload.get("sub")
            if sub:
                return {
                    "sub":       sub,
                    "user_type": user_type,
                    "email":     payload.get("email") or "",
                }
        except JWTError:
            pass  # secret incorrect ou token expiré → essai suivant

    # ── 2. Supabase Auth API (fallback réseau) ──────────────────────────────────
    try:
        response = supabase.auth.get_user(token)   # argument positionnel (toutes versions)
        if response and response.user:
            user = response.user
            user_metadata = user.user_metadata or {}
            user_type = user_metadata.get("user_type") or "client"
            return {
                "sub":       user.id,
                "user_type": user_type,
                "email":     user.email or "",
            }
    except Exception:
        pass

    raise HTTPException(status_code=401, detail="Token invalide ou expiré")
