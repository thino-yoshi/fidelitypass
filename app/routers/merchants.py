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

class RewardPayload(BaseModel):
    stamps_required: int
    description: str

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


@router.get("/me/rewards")
def get_merchant_rewards(user=Depends(get_current_user)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    res = supabase.table("merchant_rewards").select("*").eq("merchant_id", user["sub"]).order("stamps_required").execute()
    return res.data


@router.post("/me/rewards")
def create_merchant_reward(data: RewardPayload, user=Depends(get_current_user)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    if data.stamps_required <= 0:
        raise HTTPException(status_code=400, detail="stamps_required doit être supérieur à 0")

    if not data.description.strip():
        raise HTTPException(status_code=400, detail="La description ne peut pas être vide")

    existing = supabase.table("merchant_rewards").select("id", "stamps_required").eq("merchant_id", user["sub"]).execute()

    if len(existing.data) >= 5:
        raise HTTPException(status_code=400, detail="Vous ne pouvez pas avoir plus de 5 récompenses")

    used_stamps = [r["stamps_required"] for r in existing.data]
    if data.stamps_required in used_stamps:
        raise HTTPException(status_code=400, detail="Une récompense avec ce nombre de tampons existe déjà")

    res = supabase.table("merchant_rewards").insert({
        "merchant_id": user["sub"],
        "stamps_required": data.stamps_required,
        "description": data.description.strip()
    }).execute()

    return res.data[0]


@router.delete("/me/rewards/{reward_id}")
def delete_merchant_reward(reward_id: str, user=Depends(get_current_user)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    existing = supabase.table("merchant_rewards").select("id").eq("id", reward_id).eq("merchant_id", user["sub"]).execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="Récompense non trouvée")

    supabase.table("merchant_rewards").delete().eq("id", reward_id).execute()

    return {"message": "Récompense supprimée"}