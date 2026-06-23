from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from app.database import supabase
from app.dependencies import get_current_user
import uuid

router = APIRouter(tags=["Merchants"])

class MerchantCreate(BaseModel):
    business_name: str
    category: str
    stamps_required: int = 10
    reward_description: str = ""
    program_type: str = "stamps"
    points_per_euro: int = 10
    points_required: int = 100

class RewardPayload(BaseModel):
    stamps_required: int
    description: str

@router.get("/")
def get_merchants(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    res = supabase.table("merchants").select("*").range(offset, offset + limit - 1).execute()
    return res.data

@router.get("/me")
def get_my_merchant_profile(user=Depends(get_current_user)):
    """Retourne le profil complet du commerçant connecté."""
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")
    try:
        res = supabase.table("merchants").select("*").eq("id", user["sub"]).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur base de données : {str(e)}")
    if not res.data:
        raise HTTPException(status_code=404, detail="Profil commerçant non trouvé — configurez votre commerce sur qarta.be")
    return res.data[0]

@router.post("/setup")
def setup_merchant(data: MerchantCreate, user=Depends(get_current_user)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")
    
    # Vérifier si le commerçant existe déjà
    existing = supabase.table("merchants").select("id").eq("id", user["sub"]).execute()
    
    fields = {
        "business_name": data.business_name,
        "category": data.category,
        "stamps_required": data.stamps_required,
        "reward_description": data.reward_description,
        "program_type": data.program_type,
        "points_per_euro": data.points_per_euro,
        "points_required": data.points_required,
    }

    if existing.data:
        # Mettre à jour
        res = supabase.table("merchants").update(fields).eq("id", user["sub"]).execute()
    else:
        # Créer
        res = supabase.table("merchants").insert({"id": user["sub"], **fields}).execute()

    return res.data[0]


class MerchantInfo(BaseModel):
    business_name: str
    address: str = ""
    phone: str = ""
    website: str = ""
    opening_days: str = ""    # ex: "Lun,Mar,Mer,Jeu,Ven"
    opening_hours: str = ""   # ex: "11:30-22:00"
    description: str = ""


@router.post("/me/info")
def update_merchant_info(data: MerchantInfo, user=Depends(get_current_user)):
    """Met à jour les infos publiques du commerce (écran Info commerce)."""
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    existing = supabase.table("merchants").select("id").eq("id", user["sub"]).execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="Profil commerçant non trouvé — configurez votre commerce sur qarta.be")

    fields = {
        "business_name": data.business_name.strip(),
        "address": data.address.strip(),
        "phone": data.phone.strip(),
        "website": data.website.strip(),
        "opening_days": data.opening_days,
        "opening_hours": data.opening_hours,
        "description": data.description.strip(),
    }
    res = supabase.table("merchants").update(fields).eq("id", user["sub"]).execute()
    return res.data[0]


class CardDesignPayload(BaseModel):
    card_design: dict


@router.post("/me/card-design")
def save_card_design(data: CardDesignPayload, user=Depends(get_current_user)):
    """Crée ou met à jour le design visuel de la carte fidélité."""
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    existing = supabase.table("merchant_card_designs") \
        .select("id").eq("merchant_id", user["sub"]).execute()

    if existing.data:
        res = supabase.table("merchant_card_designs") \
            .update({"card_design": data.card_design}) \
            .eq("merchant_id", user["sub"]).execute()
    else:
        res = supabase.table("merchant_card_designs") \
            .insert({"merchant_id": user["sub"], "card_design": data.card_design}) \
            .execute()

    return res.data[0]


@router.get("/me/card-design")
def get_card_design(user=Depends(get_current_user)):
    """Retourne le design de carte du commerçant (créé via qarta.be)."""
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    res = supabase.table("merchant_card_designs")\
        .select("card_design, updated_at")\
        .eq("merchant_id", user["sub"])\
        .execute()

    if not res.data:
        raise HTTPException(status_code=404, detail="Aucun design de carte trouvé — créez votre carte sur qarta.be")

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


# ⚠️ Route générique TOUJOURS en dernier — sinon elle capture /me, /me/static-qr, etc.
@router.get("/{merchant_id}")
def get_merchant(merchant_id: str):
    res = supabase.table("merchants").select("*").eq("id", merchant_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Commerçant non trouvé")
    return res.data[0]