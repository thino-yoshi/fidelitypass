from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from app.database import supabase, SECRET_KEY
from jose import jwt, JWTError
import uuid

router = APIRouter(tags=["Merchants"])
security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=["HS256"])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Token invalide")

class MerchantCreate(BaseModel):
    business_name: str
    category: str
    stamps_required: int = 10
    reward_description: str = ""

@router.get("/")
def get_merchants():
    res = supabase.table("merchants").select("*").execute()
    return res.data

@router.get("/{merchant_id}")
def get_merchant(merchant_id: str):
    res = supabase.table("merchants").select("*").eq("id", merchant_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Commerçant non trouvé")
    return res.data[0]

@router.post("/setup")
def setup_merchant(data: MerchantCreate, user=Depends(get_current_user)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")
    
    # Vérifier si le commerçant existe déjà
    existing = supabase.table("merchants").select("id").eq("id", user["sub"]).execute()
    
    if existing.data:
        # Mettre à jour
        res = supabase.table("merchants").update({
            "business_name": data.business_name,
            "category": data.category,
            "stamps_required": data.stamps_required,
            "reward_description": data.reward_description
        }).eq("id", user["sub"]).execute()
    else:
        # Créer
        res = supabase.table("merchants").insert({
            "id": user["sub"],
            "business_name": data.business_name,
            "category": data.category,
            "stamps_required": data.stamps_required,
            "reward_description": data.reward_description
        }).execute()

    return res.data[0]


@router.get("/me/static-qr")
def get_static_qr(user=Depends(get_current_user)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    merchant_res = supabase.table("merchants").select("static_qr_token").eq("id", user["sub"]).execute()
    if not merchant_res.data:
        raise HTTPException(status_code=404, detail="Commerçant non trouvé")

    token = merchant_res.data[0].get("static_qr_token")
    if not token:
        token = str(uuid.uuid4())
        supabase.table("merchants").update({"static_qr_token": token}).eq("id", user["sub"]).execute()

    return {"static_qr_token": token}