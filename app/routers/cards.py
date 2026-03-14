from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from app.database import supabase, SECRET_KEY
from jose import jwt, JWTError
import uuid
from datetime import datetime, timedelta

router = APIRouter(tags=["Cards"])
security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=["HS256"])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Token invalide")

class CreateCardRequest(BaseModel):
    merchant_id: str

@router.post("/")
def create_card(data: CreateCardRequest, user=Depends(get_current_user)):
    client_id = user["sub"]
    existing = supabase.table("loyalty_cards").select("id").eq("client_id", client_id).eq("merchant_id", data.merchant_id).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Carte déjà existante pour ce commerce")
    qr_token = str(uuid.uuid4())
    card = supabase.table("loyalty_cards").insert({
        "client_id": client_id,
        "merchant_id": data.merchant_id,
        "stamps_count": 0,
        "qr_token": qr_token
    }).execute()
    return card.data[0]

@router.get("/me")
def get_my_cards(user=Depends(get_current_user)):
    client_id = user["sub"]
    cards = supabase.table("loyalty_cards").select(
        "*, merchants(business_name, category, stamps_required, reward_description)"
    ).eq("client_id", client_id).execute()
    return cards.data if cards.data else []

@router.get("/qr/{card_id}")
def get_dynamic_qr(card_id: str, user=Depends(get_current_user)):
    # Vérifier que la carte appartient bien à ce client
    card = supabase.table("loyalty_cards").select("*").eq("id", card_id).eq("client_id", user["sub"]).execute()
    if not card.data:
        raise HTTPException(status_code=404, detail="Carte non trouvée")
    
    # Générer un token JWT qui expire dans 60s
    payload = {
        "qr_token": card.data[0]["qr_token"],
        "card_id": card_id,
        "exp": datetime.utcnow() + timedelta(seconds=60)
    }
    dynamic_token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")

    return {"dynamic_token": dynamic_token, "expires_in": 60}

@router.get("/scan-history")
def get_scan_history(user=Depends(get_current_user)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    res = supabase.table("scan_history")\
        .select("*")\
        .eq("merchant_id", user["sub"])\
        .order("scanned_at", desc=True)\
        .limit(50)\
        .execute()

    results = []
    for scan in res.data:
        client_res = supabase.table("users")\
            .select("name, email")\
            .eq("id", scan["client_id"])\
            .execute()
        client = client_res.data[0] if client_res.data else {}
        scan["users"] = client
        results.append(scan)

    return results

@router.get("/stats")
def get_merchant_stats(user=Depends(get_current_user)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    cards_res = supabase.table("loyalty_cards")\
        .select("*")\
        .eq("merchant_id", user["sub"])\
        .execute()

    cards = cards_res.data
    total_clients = len(cards)
    total_stamps = sum(c["stamps_count"] for c in cards)

    rewards_res = supabase.table("scan_history")\
        .select("id")\
        .eq("merchant_id", user["sub"])\
        .eq("reward_reached", True)\
        .execute()
    total_rewards = len(rewards_res.data)

    scans_res = supabase.table("scan_history")\
        .select("id")\
        .eq("merchant_id", user["sub"])\
        .execute()
    total_scans = len(scans_res.data)

    return {
        "total_clients": total_clients,
        "total_stamps": total_stamps,
        "total_rewards": total_rewards,
        "total_scans": total_scans,
    }