from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from app.database import supabase, SECRET_KEY
from app.dependencies import get_current_user

router = APIRouter(tags=["Rewards"])


class RedeemRequest(BaseModel):
    qr_token: str


@router.get("/me")
def my_rewards(user=Depends(get_current_user)):
    """Récompenses DISPONIBLES (non utilisées) du client, triées de la plus
    ancienne à la plus récente (FIFO), enrichies du nom du magasin."""
    res = (
        supabase.table("rewards")
        .select("*")
        .eq("client_id", user["sub"])
        .is_("redeemed_at", "null")
        .order("earned_at")
        .execute()
    )
    rewards = res.data or []
    merchant_ids = list({r["merchant_id"] for r in rewards})
    names = {}
    if merchant_ids:
        m = supabase.table("merchants").select("id, business_name").in_("id", merchant_ids).execute()
        names = {x["id"]: x["business_name"] for x in (m.data or [])}
    for r in rewards:
        r["merchant_name"] = names.get(r["merchant_id"], "Commerce")
    return rewards


@router.get("/{reward_id}/qr")
def reward_qr(reward_id: str, user=Depends(get_current_user)):
    """Génère un QR dynamique (JWT 120s) pour faire valider la récompense au commerce."""
    res = supabase.table("rewards").select("*").eq("id", reward_id).eq("client_id", user["sub"]).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Récompense introuvable")
    r = res.data[0]
    if r.get("redeemed_at"):
        raise HTTPException(status_code=400, detail="Récompense déjà utilisée")

    payload = {
        "type": "reward",
        "reward_id": reward_id,
        "exp": datetime.utcnow() + timedelta(seconds=120),
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")
    return {"dynamic_token": token, "expires_in": 120}


@router.post("/redeem")
def redeem_reward(data: RedeemRequest, user=Depends(get_current_user)):
    """Le commerçant valide une récompense en scannant son QR."""
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    try:
        decoded = jwt.decode(data.qr_token, SECRET_KEY, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status_code=400, detail="QR récompense invalide ou expiré")

    if decoded.get("type") != "reward":
        raise HTTPException(status_code=400, detail="Ce QR n'est pas une récompense")

    reward_id = decoded.get("reward_id")
    res = supabase.table("rewards").select("*").eq("id", reward_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Récompense introuvable")
    r = res.data[0]
    if r["merchant_id"] != user["sub"]:
        raise HTTPException(status_code=403, detail="Cette récompense n'est pas pour votre commerce")
    if r.get("redeemed_at"):
        raise HTTPException(status_code=400, detail="Récompense déjà utilisée")

    supabase.table("rewards").update(
        {"redeemed_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", reward_id).execute()

    client = supabase.table("users").select("name, email").eq("id", r["client_id"]).execute().data
    cname = (client[0].get("name") or client[0].get("email")) if client else "Client"

    return {
        "success": True,
        "description": r.get("description") or "Récompense",
        "client_name": cname,
    }
