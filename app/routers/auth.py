from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.database import supabase, SECRET_KEY
import bcrypt
import uuid
from jose import jwt
from datetime import datetime, timedelta

router = APIRouter()

class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str
    user_type: str

class LoginRequest(BaseModel):
    email: str
    password: str

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