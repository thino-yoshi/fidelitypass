from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from app.database import supabase, SECRET_KEY
from jose import jwt, JWTError
import uuid

router = APIRouter(prefix="/cards", tags=["Cards"])
security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=["HS256"])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Token invalide")

class CardCreate(BaseModel):
    merchant_id: str

@router.post("/")
def create_card(data: CardCreate, user=Depends(get_current_user)):
    if user["user_type"] != "client":
        raise HTTPException(status_code=403, detail="Réservé aux clients")
    existing = supabase.table("loyalty_cards").select("*")\
        .eq("client_id", user["sub"])\
        .eq("merchant_id", data.merchant_id).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Carte déjà existante")
    qr_token = str(uuid.uuid4())
    res = supabase.table("loyalty_cards").insert({
        "client_id": user["sub"],
        "merchant_id": data.merchant_id,
        "stamps_count": 0,
        "qr_token": qr_token
    }).execute()
    return res.data[0]

@router.get("/me")
def get_my_cards(user=Depends(get_current_user)):
    res = supabase.table("loyalty_cards").select("*")\
        .eq("client_id", user["sub"]).execute()
    return res.data