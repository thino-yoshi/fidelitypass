from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.dependencies import get_current_user
from app.database import supabase
import os
import json
import firebase_admin
from firebase_admin import credentials, messaging

router = APIRouter(tags=["Notifications"])

# Init Firebase Admin (une seule fois)
if not firebase_admin._apps:
    service_account = os.getenv("FIREBASE_SERVICE_ACCOUNT")
    if service_account:
        cred_dict = json.loads(service_account)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)

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

    # Envoyer via Firebase Admin SDK V1
    sent = 0
    for token in tokens:
        try:
            message = messaging.Message(
                notification=messaging.Notification(
                    title=data.title,
                    body=data.message,
                ),
                data={
                    "type": "promo",
                    "merchant_id": user["sub"]
                },
                token=token,
            )
            messaging.send(message)
            sent += 1
        except Exception as e:
            print(f"❌ Erreur envoi FCM: {e}")

    return {"sent": sent, "message": f"{sent} notification(s) envoyée(s)"}