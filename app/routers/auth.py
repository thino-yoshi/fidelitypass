from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.database import supabase, SECRET_KEY
import bcrypt
import uuid
from jose import jwt
from datetime import datetime, timedelta
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

router = APIRouter()

class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str
    user_type: str

class LoginRequest(BaseModel):
    email: str
    password: str

class GoogleAuthRequest(BaseModel):
    id_token: str


def create_token(user_id: str, user_type: str):
    payload = {
        "sub": user_id,
        "user_type": user_type,
        "exp": datetime.utcnow() + timedelta(days=7)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

@router.post("/register")
def register(data: RegisterRequest):
    existing = supabase.table("users").select("id").eq("email", data.email).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Email déjà utilisé")
    
    password_hash = bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode()
    
    user = supabase.table("users").insert({
        "email": data.email,
        "password_hash": password_hash,
        "user_type": data.user_type,
        "name": data.name
    }).execute()
    
    user_id = user.data[0]["id"]
    token = create_token(user_id, data.user_type)
    
    return {"token": token, "user_type": data.user_type, "name": data.name}

@router.post("/login")
def login(data: LoginRequest):
    user = supabase.table("users").select("*").eq("email", data.email).execute()
    
    if not user.data:
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
    
    user_data = user.data[0]
    
    if not bcrypt.checkpw(data.password.encode(), user_data["password_hash"].encode()):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
    
    token = create_token(user_data["id"], user_data["user_type"])
    
    return {"token": token, "user_type": user_data["user_type"], "name": user_data["name"]}

@router.post("/google")
def google_login(data: GoogleAuthRequest):
    try:
        # Vérifier le token Google
        idinfo = id_token.verify_oauth2_token(
            data.id_token,
            google_requests.Request(),
        )
        
        email = idinfo['email']
        name = idinfo.get('name', email)
        
        # Chercher si l'utilisateur existe déjà
        existing = supabase.table("users").select("*").eq("email", email).execute()
        
        if existing.data:
            user = existing.data[0]
        else:
            # Créer un nouvel utilisateur
            new_user = supabase.table("users").insert({
                "email": email,
                "name": name,
                "user_type": "client",
                "password_hash": "google_oauth"
            }).execute()
            user = new_user.data[0]
        
        # Générer un JWT
        token = jwt.encode(
            {"sub": user["id"], "user_type": user["user_type"]},
            SECRET_KEY,
            algorithm="HS256"
        )
        
        return {
            "token": token,
            "user_type": user["user_type"],
            "name": user["name"]
        }
        
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token Google invalide: {str(e)}")