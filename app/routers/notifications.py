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


def _send_fcm_to_clients(title: str, message: str, client_ids: list, merchant_id: str, notif_type: str = "promo") -> int:
    """Envoie une notification FCM à une liste de client_ids. Retourne le nb de succès."""
    if not client_ids:
        return 0
    tokens_res = supabase.table("users")\
        .select("fcm_token")\
        .in_("id", client_ids)\
        .not_.is_("fcm_token", "null")\
        .execute()
    tokens = [u["fcm_token"] for u in tokens_res.data if u.get("fcm_token")]
    sent = 0
    for token in tokens:
        try:
            msg = messaging.Message(
                notification=messaging.Notification(title=title, body=message),
                data={"type": notif_type, "merchant_id": merchant_id},
                token=token,
            )
            messaging.send(msg)
            sent += 1
        except Exception as e:
            print(f"❌ FCM error: {e}")
    return sent


# ── Broadcast ─────────────────────────────────────────────────────────────────

class NotificationPayload(BaseModel):
    title: str
    message: str

@router.post("/send")
async def send_notification(data: NotificationPayload, user=Depends(get_current_user)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    cards = supabase.table("loyalty_cards")\
        .select("client_id")\
        .eq("merchant_id", user["sub"])\
        .execute()

    if not cards.data:
        return {"sent": 0, "message": "Aucun client à notifier"}

    client_ids = [c["client_id"] for c in cards.data]
    sent = _send_fcm_to_clients(data.title, data.message, client_ids, user["sub"], "promo")
    return {"sent": sent, "message": f"{sent} notification(s) envoyée(s)"}


# ── Push ciblé ────────────────────────────────────────────────────────────────

class TargetedNotificationPayload(BaseModel):
    title: str
    message: str
    max_stamps_remaining: Optional[int] = None
    inactive_days: Optional[int] = None

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
        if data.max_stamps_remaining is not None:
            remaining = stamps_required - card["stamps_count"]
            if remaining > data.max_stamps_remaining:
                continue
        if data.inactive_days is not None:
            since = (datetime.now(timezone.utc) - timedelta(days=data.inactive_days)).isoformat()
            last_scan = supabase.table("scan_history")\
                .select("scanned_at")\
                .eq("merchant_id", user["sub"])\
                .eq("client_id", card["client_id"])\
                .gte("scanned_at", since)\
                .execute()
            if last_scan.data:
                continue
        target_client_ids.append(card["client_id"])

    if not target_client_ids:
        return {"sent": 0, "message": "Aucun client correspond aux critères"}

    sent = _send_fcm_to_clients(data.title, data.message, target_client_ids, user["sub"], "targeted")
    return {"sent": sent, "total_targeted": len(target_client_ids), "message": f"{sent}/{len(target_client_ids)} notification(s) envoyée(s)"}


# ── Notifications planifiées ──────────────────────────────────────────────────

class SchedulePayload(BaseModel):
    title: str
    message: str
    scheduled_at: str          # ISO8601 string, e.g. "2025-04-01T18:00:00+02:00"
    filter_type: str = "broadcast"  # "broadcast" | "stamps" | "inactive"
    filter_value: Optional[int] = None

@router.post("/schedule")
async def schedule_notification(data: SchedulePayload, user=Depends(get_current_user)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    try:
        scheduled_dt = datetime.fromisoformat(data.scheduled_at)
        if scheduled_dt.tzinfo is None:
            scheduled_dt = scheduled_dt.replace(tzinfo=timezone.utc)
        scheduled_dt = scheduled_dt.astimezone(timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail="Format de date invalide")

    if scheduled_dt <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="La date doit être dans le futur")

    res = supabase.table("scheduled_notifications").insert({
        "merchant_id": user["sub"],
        "title": data.title,
        "message": data.message,
        "scheduled_at": scheduled_dt.isoformat(),
        "filter_type": data.filter_type,
        "filter_value": data.filter_value,
        "sent": False,
    }).execute()

    return {"id": res.data[0]["id"], "message": "Notification planifiée avec succès"}


@router.get("/scheduled")
async def get_scheduled(user=Depends(get_current_user)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    res = supabase.table("scheduled_notifications")\
        .select("*")\
        .eq("merchant_id", user["sub"])\
        .eq("sent", False)\
        .order("scheduled_at")\
        .execute()

    return res.data


@router.delete("/scheduled/{notif_id}")
async def cancel_scheduled(notif_id: str, user=Depends(get_current_user)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    res = supabase.table("scheduled_notifications")\
        .select("id")\
        .eq("id", notif_id)\
        .eq("merchant_id", user["sub"])\
        .execute()

    if not res.data:
        raise HTTPException(status_code=404, detail="Notification introuvable")

    supabase.table("scheduled_notifications")\
        .delete()\
        .eq("id", notif_id)\
        .execute()

    return {"message": "Notification annulée"}


# ── Job APScheduler (appelé depuis main.py) ───────────────────────────────────

def send_due_notifications():
    """Vérifie et envoie les notifications planifiées dont l'heure est passée."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        res = supabase.table("scheduled_notifications")\
            .select("*")\
            .eq("sent", False)\
            .lte("scheduled_at", now)\
            .execute()

        for notif in res.data:
            merchant_id = notif["merchant_id"]
            title = notif["title"]
            message = notif["message"]
            filter_type = notif.get("filter_type", "broadcast")
            filter_value = notif.get("filter_value")

            # Récupérer les clients cibles
            cards_res = supabase.table("loyalty_cards")\
                .select("client_id, stamps_count")\
                .eq("merchant_id", merchant_id)\
                .execute()

            client_ids = []
            if filter_type == "broadcast":
                client_ids = [c["client_id"] for c in cards_res.data]
            elif filter_type == "stamps" and filter_value is not None:
                merchant_res = supabase.table("merchants").select("stamps_required").eq("id", merchant_id).execute()
                stamps_req = merchant_res.data[0]["stamps_required"] if merchant_res.data else 10
                for card in cards_res.data:
                    if (stamps_req - card["stamps_count"]) <= filter_value:
                        client_ids.append(card["client_id"])
            elif filter_type == "inactive" and filter_value is not None:
                since = (datetime.now(timezone.utc) - timedelta(days=filter_value)).isoformat()
                for card in cards_res.data:
                    last_scan = supabase.table("scan_history")\
                        .select("scanned_at")\
                        .eq("merchant_id", merchant_id)\
                        .eq("client_id", card["client_id"])\
                        .gte("scanned_at", since)\
                        .execute()
                    if not last_scan.data:
                        client_ids.append(card["client_id"])

            sent = _send_fcm_to_clients(title, message, client_ids, merchant_id, "scheduled")
            print(f"✅ Scheduled notif {notif['id']}: {sent} envoyée(s)")

            # Marquer comme envoyée
            supabase.table("scheduled_notifications")\
                .update({"sent": True})\
                .eq("id", notif["id"])\
                .execute()

    except Exception as e:
        print(f"❌ Erreur job scheduler: {e}")
