from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from app.database import supabase, db, SECRET_KEY
from app.limiter import limiter
from app.logger import get_logger
import bcrypt
import uuid
import httpx
from jose import jwt
from datetime import datetime, timedelta
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import secrets
import string
import os

GOOGLE_CLIENT_ID  = os.getenv("GOOGLE_CLIENT_ID")
SUPABASE_URL      = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", os.getenv("SUPABASE_SERVICE_KEY", ""))
logger = get_logger("auth")

router = APIRouter()

class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str
    user_type: str
    merchant_code: str = None

class LoginRequest(BaseModel):
    email: str
    password: str

class GoogleAuthRequest(BaseModel):
    id_token: str

class MerchantCodeRequest(BaseModel):
    email: str

class ValidateCodeRequest(BaseModel):
    email: str
    code: str

def create_token(user_id: str, user_type: str):
    payload = {
        "sub": user_id,
        "user_type": user_type,
        "exp": datetime.utcnow() + timedelta(days=7)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

@router.post("/register")
@limiter.limit("10/minute")
def register(request: Request, data: RegisterRequest):
    existing = db.table("users").select("id").eq("email", data.email).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Email déjà utilisé")

    # Vérifier le code commerçant si user_type == merchant
    if data.user_type == "merchant":
        if not data.merchant_code:
            raise HTTPException(status_code=400, detail="Code commerçant requis")

        code_res = db.table("merchant_codes")\
            .select("*")\
            .eq("code", data.merchant_code.upper())\
            .eq("email", data.email.lower())\
            .eq("used", False)\
            .execute()

        if not code_res.data:
            raise HTTPException(status_code=400, detail="Code commerçant invalide, expiré ou déjà utilisé")

    password_hash = bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode()

    user = db.table("users").insert({
        "email": data.email,
        "password_hash": password_hash,
        "user_type": data.user_type,
        "name": data.name
    }).execute()

    user_id = user.data[0]["id"]

    # Marquer le code comme utilisé si commerçant
    if data.user_type == "merchant":
        db.table("merchant_codes")\
            .update({"used": True, "used_at": datetime.utcnow().isoformat()})\
            .eq("code", data.merchant_code.upper())\
            .execute()

    token = create_token(user_id, data.user_type)
    logger.info(f"REGISTER email={data.email} user_type={data.user_type}")
    return {"token": token, "user_type": data.user_type, "name": data.name}

@router.post("/login")
@limiter.limit("10/minute")
def login(request: Request, data: LoginRequest):
    result = db.table("users").select("*").eq("email", data.email).execute()

    if not result.data:
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")

    # S'il y a un doublon (compte site web SUPABASE_AUTH + compte app bcrypt),
    # préférer le compte app (bcrypt) — l'app gère ses propres comptes via Neon
    user_list = result.data
    user_data = next(
        (u for u in user_list if u["password_hash"] not in ("SUPABASE_AUTH", "google_oauth")),
        user_list[0]
    )

    if user_data["password_hash"] in ("SUPABASE_AUTH", "google_oauth"):
        raise HTTPException(status_code=401, detail="Ce compte utilise une connexion Google ou Apple")

    if not bcrypt.checkpw(data.password.encode(), user_data["password_hash"].encode()):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")

    token = create_token(user_data["id"], user_data["user_type"])
    logger.info(f"LOGIN email={data.email} user_type={user_data['user_type']}")
    return {"token": token, "user_type": user_data["user_type"], "name": user_data["name"]}

@router.post("/google")
@limiter.limit("10/minute")
def google_login(request: Request, data: GoogleAuthRequest):
    try:
        idinfo = id_token.verify_oauth2_token(
            data.id_token,
            google_requests.Request(),
        )

        email = idinfo['email']
        name = idinfo.get('name', email)

        existing = db.table("users").select("*").eq("email", email).execute()

        if existing.data:
            user = existing.data[0]
        else:
            new_user = db.table("users").insert({
                "email": email,
                "name": name,
                "user_type": "client",
                "password_hash": "google_oauth"
            }).execute()
            user = new_user.data[0]

        token = create_token(user["id"], user["user_type"])

        return {
            "token": token,
            "user_type": user["user_type"],
            "name": user["name"],
            "email": user["email"],
            "is_google": True
        }

    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token Google invalide: {str(e)}")

@router.post("/generate-merchant-code")
@limiter.limit("5/minute")
def generate_merchant_code(request: Request, data: MerchantCodeRequest):
    alphabet = string.ascii_uppercase + string.digits
    code = ''.join(secrets.choice(alphabet) for _ in range(8))

    db.table("merchant_codes").insert({
        "code": code,
        "email": data.email,
        "used": False
    }).execute()

    return {"code": code, "email": data.email}

class AdminResetPasswordRequest(BaseModel):
    email: str
    new_password: str
    admin_key: str

@router.post("/admin/reset-password")
def admin_reset_password(data: AdminResetPasswordRequest):
    """Reset le mot de passe d'un utilisateur — réservé admin."""
    if data.admin_key != SECRET_KEY:
        raise HTTPException(status_code=403, detail="Clé admin invalide")
    user = db.table("users").select("id").eq("email", data.email).execute()
    if not user.data:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
    new_hash = bcrypt.hashpw(data.new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    db.table("users").update({"password_hash": new_hash}).eq("email", data.email).execute()
    logger.info(f"ADMIN RESET PASSWORD email={data.email}")
    return {"success": True}

class AdminMerchantRequest(BaseModel):
    email: str
    password: str
    name: str
    admin_key: str

@router.post("/admin/create-merchant")
def admin_create_merchant(data: AdminMerchantRequest):
    """Crée un compte commerçant directement — réservé admin (admin_key = SECRET_KEY)."""
    if data.admin_key != SECRET_KEY:
        raise HTTPException(status_code=403, detail="Clé admin invalide")
    existing = db.table("users").select("id").eq("email", data.email).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Email déjà utilisé")
    password_hash = bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode()
    user = db.table("users").insert({
        "email": data.email,
        "password_hash": password_hash,
        "user_type": "merchant",
        "name": data.name,
    }).execute()
    user_id = user.data[0]["id"]
    token = create_token(user_id, "merchant")
    logger.info(f"ADMIN CREATE MERCHANT email={data.email}")
    return {"token": token, "user_type": "merchant", "name": data.name}

@router.post("/validate-merchant-code")
def validate_merchant_code(data: ValidateCodeRequest):
    res = db.table("merchant_codes")\
        .select("*")\
        .eq("code", data.code.upper())\
        .eq("email", data.email.lower())\
        .eq("used", False)\
        .execute()

    if not res.data:
        raise HTTPException(status_code=400, detail="Code invalide, expiré ou déjà utilisé")

    return {"valid": True, "message": "Code valide !"}