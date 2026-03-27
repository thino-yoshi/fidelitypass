from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.dependencies import get_current_user
from app.database import supabase
import os
import json
import firebase_admin
from firebase_admin import credentials, messaging
from datetime import datetime, timedelta, timezone

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


class TargetedNotificationPayload(BaseModel):
    title: str
    message: str
    max_stamps_remaining: Optional[int] = None  # envoyer si tampons restants <= N
    inactive_days: Optional[int] = None          # envoyer si pas de visite depuis N jours


@router.post("/send-targeted")
async def send_targeted_notification(data: TargetedNotificationPayload, user=Depends(get_current_user)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    merchant_res = supabase.table("merchants").select("stamps_required").eq("id", user["sub"]).execute()
    stamps_required = merchant_res.data[0]["stamps_required"] if merchant_res.data else 10

    cards_res = supabase.table("loyalty_cards").select("*").eq("merchant_id", user["sub"]).execute()
    if not cards_res.data:
        return {"sent": 0, "message": "Aucun client"}

    target_client_ids = []
    for card in cards_res.data:
        # Filtre tampons restants
        if data.max_stamps_remaining is not None:
            remaining = stamps_required - card["stamps_count"]
            if remaining > data.max_stamps_remaining:
                continue

        # Filtre inactivité
        if data.inactive_days is not None:
            since = (datetime.now(timezone.utc) - timedelta(days=data.inactive_days)).isoformat()
            last_scan = supabase.table("scan_history")\
                .select("scanned_at")\
                .eq("merchant_id", user["sub"])\
                .eq("client_id", card["client_id"])\
                .gte("scanned_at", since)\
                .execute()
            if last_scan.data:
                continue  # Client actif → on ne l'envoie pas

        target_client_ids.append(card["client_id"])

    if not target_client_ids:
        return {"sent": 0, "message": "Aucun client correspond aux critères"}

    tokens_res = supabase.table("users")\
        .select("fcm_token")\
        .in_("id", target_client_ids)\
        .not_.is_("fcm_token", "null")\
        .execute()

    tokens = [u["fcm_token"] for u in tokens_res.data if u.get("fcm_token")]
    if not tokens:
        return {"sent": 0, "message": "Aucun token FCM disponible"}

    sent = 0
    for token in tokens:
        try:
            message = messaging.Message(
                notification=messaging.Notification(title=data.title, body=data.message),
                data={"type": "targeted", "merchant_id": user["sub"]},
                token=token,
            )
            messaging.send(message)
            sent += 1
        except Exception as e:
            print(f"❌ Erreur FCM: {e}")

    return {"sent": sent, "total_targeted": len(target_client_ids), "message": f"{sent}/{len(target_client_ids)} notification(s) envoyée(s)"}