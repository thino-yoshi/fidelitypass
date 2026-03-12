from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from app.database import supabase, SECRET_KEY
from jose import jwt, JWTError

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
def scan_qr(data: ScanRequest, user=Depends(get_current_user)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    res = supabase.table("loyalty_cards").select("*")\
        .eq("qr_token", data.qr_token).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="QR code invalide")

    card = res.data[0]

    if card["merchant_id"] != user["sub"]:
        raise HTTPException(status_code=403, detail="Cette carte n'appartient pas à votre commerce")

    merchant_res = supabase.table("merchants").select("*")\
        .eq("id", user["sub"]).execute()
    merchant = merchant_res.data[0]

    new_count = card["stamps_count"] + 1
    reward_reached = new_count >= merchant["stamps_required"]

    if reward_reached:
        new_count = 0

    supabase.table("loyalty_cards").update({"stamps_count": new_count})\
        .eq("id", card["id"]).execute()

    return {
        "success": True,
        "stamps_count": new_count,
        "stamps_required": merchant["stamps_required"],
        "reward_reached": reward_reached,
        "message": "🎉 Récompense débloquée !" if reward_reached else f"Tampon ajouté ! {new_count}/{merchant['stamps_required']}"
    }