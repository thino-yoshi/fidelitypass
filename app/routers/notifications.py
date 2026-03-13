from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.dependencies import get_current_user
from app.database import supabase
import httpx
import os

router = APIRouter(tags=["Notifications"])

class NotificationPayload(BaseModel):
    title: str
    message: str

@router.post("/send")
async def send_notification(data: NotificationPayload, user=Depends(get_current_user)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")
    
    # Récupérer tous les clients qui ont une carte chez ce commerçant
    cards = supabase.table("loyalty_cards")\
        .select("client_id")\
        .eq("merchant_id", user["sub"])\
        .execute()
    
    if not cards.data:
        return {"sent": 0, "message": "Aucun client à notifier"}
    
    client_ids = [c["client_id"] for c in cards.data]
    
    # Récupérer les FCM tokens des clients
    tokens_res = supabase.table("users")\
        .select("fcm_token")\
        .in_("id", client_ids)\
        .not_.is_("fcm_token", "null")\
        .execute()
    
    tokens = [u["fcm_token"] for u in tokens_res.data if u.get("fcm_token")]
    
    if not tokens:
        return {"sent": 0, "message": "Aucun token FCM disponible"}
    
    # Envoyer via Firebase
    firebase_key = os.getenv("FIREBASE_SERVER_KEY")
    sent = 0
    
    async with httpx.AsyncClient() as client:
        for token in tokens:
            res = await client.post(
                "https://fcm.googleapis.com/fcm/send",
                headers={
                    "Authorization": f"key={firebase_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "to": token,
                    "notification": {
                        "title": data.title,
                        "body": data.message
                    },
                    "data": {
                        "type": "promo",
                        "merchant_id": user["sub"]
                    }
                }
            )
            if res.status_code == 200:
                sent += 1
    
    return {"sent": sent, "message": f"{sent} notification(s) envoyée(s)"}