from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from app.database import supabase, SECRET_KEY
from jose import jwt, JWTError

router = APIRouter()

def get_user_from_token(authorization: str):
    try:
        token = authorization.replace("Bearer ", "")
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Token invalide")

class ScanRequest(BaseModel):
    qr_token: str

@router.post("/")
def scan_qr(data: ScanRequest, authorization: str = Header(...)):
    user = get_user_from_token(authorization)
    
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")
    
    merchant_id = user["sub"]
    
    card = supabase.table("loyalty_cards").select("*").eq(
        "qr_token", data.qr_token
    ).execute()
    
    if not card.data:
        raise HTTPException(status_code=404, detail="QR code invalide")
    
    card_data = card.data[0]
    
    if card_data["merchant_id"] != merchant_id:
        raise HTTPException(status_code=403, detail="Cette carte n'appartient pas à votre commerce")
    
    merchant = supabase.table("merchants").select("stamps_required").eq(
        "id", merchant_id
    ).execute()
    
    stamps_required = merchant.data[0]["stamps_required"]
    new_stamps = card_data["stamps_count"] + 1
    reward_reached = new_stamps >= stamps_required
    
    if reward_reached:
        new_stamps = 0
    
    supabase.table("loyalty_cards").update({
        "stamps_count": new_stamps
    }).eq("id", card_data["id"]).execute()
    
    return {
        "success": True,
        "stamps_count": new_stamps,
        "reward_reached": reward_reached,
        "message": "Récompense atteinte ! 🎉" if reward_reached else f"Tampon ajouté ! {new_stamps}/{stamps_required}"
    }