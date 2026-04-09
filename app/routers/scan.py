from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from app.database import supabase, SECRET_KEY
from app.main import limiter
from app.logger import get_logger
from jose import jwt, JWTError

logger = get_logger("scan")

router = APIRouter(tags=["Scan"])
security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=["HS256"])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Token invalide")

class ScanRequest(BaseModel):
    qr_token: str

@router.post("/")
@limiter.limit("60/minute")
def scan_qr(request: Request, data: ScanRequest, user=Depends(get_current_user)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    # Essayer de décoder comme JWT dynamique d'abord
    real_qr_token = data.qr_token
    try:
        decoded = jwt.decode(data.qr_token, SECRET_KEY, algorithms=["HS256"])
        real_qr_token = decoded.get("qr_token", data.qr_token)
    except JWTError:
        # Pas un JWT → on utilise le token tel quel (rétro-compatibilité)
        pass

    res = supabase.table("loyalty_cards").select("*").eq("qr_token", real_qr_token).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="QR code invalide ou expiré")

    card = res.data[0]

    if card["merchant_id"] != user["sub"]:
        raise HTTPException(status_code=403, detail="Cette carte n'appartient pas à votre commerce")

    merchant_res = supabase.table("merchants").select("*").eq("id", user["sub"]).execute()
    merchant = merchant_res.data[0]

    new_count = card["stamps_count"] + 1
    reward_reached = new_count >= merchant["stamps_required"]
    if reward_reached:
        new_count = 0

    supabase.table("loyalty_cards").update({"stamps_count": new_count}).eq("id", card["id"]).execute()

    supabase.table("scan_history").insert({
        "merchant_id": user["sub"],
        "client_id": card["client_id"],
        "card_id": card["id"],
        "stamps_count": new_count,
        "reward_reached": reward_reached
    }).execute()

    # Insert client notification
    if reward_reached:
        notif_type = "recompense"
        notif_title = "🎉 Récompense débloquée !"
        notif_body = f"Bravo ! Tu as gagné ta récompense chez {merchant['business_name']}."
    else:
        remaining = merchant["stamps_required"] - new_count
        notif_type = "tampon"
        notif_title = "✓ Tampon ajouté !"
        notif_body = f"{new_count}/{merchant['stamps_required']} tampons. Plus que {remaining} pour ta récompense !"

    try:
        supabase.table("client_notifications").insert({
            "client_id": card["client_id"],
            "merchant_id": user["sub"],
            "merchant_name": merchant["business_name"],
            "title": notif_title,
            "body": notif_body,
            "type": notif_type,
            "read": False,
        }).execute()
    except Exception as e:
        print(f"❌ Erreur insertion client_notifications: {e}")

    if reward_reached:
        logger.info(f"REWARD merchant={user['sub']} client={card['client_id']} card={card['id']}")
    else:
        logger.info(f"SCAN merchant={user['sub']} client={card['client_id']} stamps={new_count}/{merchant['stamps_required']}")

    return {
        "success": True,
        "stamps_count": new_count,
        "stamps_required": merchant["stamps_required"],
        "reward_reached": reward_reached,
        "message": "🎉 Récompense débloquée !" if reward_reached else f"Tampon ajouté ! {new_count}/{merchant['stamps_required']}"
    }
