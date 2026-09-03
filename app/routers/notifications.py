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


def _send_fcm_to_clients(
    title: str,
    message: str,
    client_ids: list,
    merchant_id: str,
    merchant_name: str,
    notif_type: str = "promo",
    notif_category: str = "offre",  # "offre" | "visite" | "general"
) -> int:
    """Envoie une notification FCM à une liste de client_ids. Retourne le nb de succès."""
    if not client_ids:
        return 0
    try:
        users_res = supabase.table("users")\
            .select("id, fcm_token, notif_push, notif_offres, notif_visites")\
            .in_("id", client_ids)\
            .execute()
        users_data = [u for u in (users_res.data or []) if u.get("fcm_token")]
    except Exception as e:
        print(f"⚠️ Erreur fetch prefs notif: {e}")
        users_data = []



    # Filtre selon les préférences de chaque client
    def _allowed(u: dict) -> bool:
        if u.get("notif_push") is False:
            return False
        if notif_category == "offre" and u.get("notif_offres") is False:
            return False
        if notif_category == "visite" and not u.get("notif_visites"):
            return False
        return True

    tokens = [u["fcm_token"] for u in users_data if _allowed(u)]
    allowed_ids = {u["id"] for u in users_data if _allowed(u)}
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

    # Batch insert into client_notifications uniquement pour les clients autorisés
    try:
        records = [
            {
                "client_id": client_id,
                "merchant_id": merchant_id,
                "merchant_name": merchant_name,
                "title": title,
                "body": message,
                "type": notif_type,
                "read": False,
            }
            for client_id in client_ids if client_id in allowed_ids
        ]
        if records:
            supabase.table("client_notifications").insert(records).execute()
    except Exception as e:
        print(f"❌ Erreur insertion client_notifications (batch): {e}")

    return sent


# ── Préférences de notification ───────────────────────────────────────────────

class NotifPrefsPayload(BaseModel):
    notif_push: bool
    notif_offres: bool
    notif_visites: bool

@router.put("/preferences")
async def update_notif_preferences(data: NotifPrefsPayload, user=Depends(get_current_user)):
    if user["user_type"] != "client":
        raise HTTPException(status_code=403, detail="Réservé aux clients")
    supabase.table("users").update({
        "notif_push":    data.notif_push,
        "notif_offres":  data.notif_offres,
        "notif_visites": data.notif_visites,
    }).eq("id", user["sub"]).execute()
    return {"message": "ok"}


# ── Broadcast ─────────────────────────────────────────────────────────────────

class NotificationPayload(BaseModel):
    title: str
    message: str

@router.post("/send")
async def send_notification(data: NotificationPayload, user=Depends(get_current_user)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    merchant_res = supabase.table("merchants").select("business_name").eq("id", user["sub"]).execute()
    merchant_name = merchant_res.data[0]["business_name"] if merchant_res.data else ""

    cards = supabase.table("loyalty_cards")\
        .select("client_id")\
        .eq("merchant_id", user["sub"])\
        .execute()

    if not cards.data:
        return {"sent": 0, "message": "Aucun client à notifier"}

    client_ids = [c["client_id"] for c in cards.data]
    sent = _send_fcm_to_clients(data.title, data.message, client_ids, user["sub"], merchant_name, "promo", notif_category="offre")
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

    merchant_res = supabase.table("merchants").select("business_name, stamps_required").eq("id", user["sub"]).execute()
    merchant_name = merchant_res.data[0]["business_name"] if merchant_res.data else ""
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

    # inactive_days = rappel de visite, max_stamps_remaining = offre proche récompense
    cat = "visite" if data.inactive_days is not None else "offre"
    sent = _send_fcm_to_clients(data.title, data.message, target_client_ids, user["sub"], merchant_name, "targeted", notif_category=cat)
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


# ── Notifications client ───────────────────────────────────────────────────────

@router.get("/client")
async def get_client_notifications(user=Depends(get_current_user)):
    """Retourne les notifications du client connecté, les plus récentes en premier."""
    if user["user_type"] != "client":
        raise HTTPException(status_code=403, detail="Réservé aux clients")
    res = supabase.table("client_notifications")\
        .select("*")\
        .eq("client_id", user["sub"])\
        .order("created_at", desc=True)\
        .limit(50)\
        .execute()
    return res.data


@router.put("/client/read-all")
async def mark_all_client_notifications_read(user=Depends(get_current_user)):
    """Marque toutes les notifications non lues du client connecté comme lues."""
    if user["user_type"] != "client":
        raise HTTPException(status_code=403, detail="Réservé aux clients")
    supabase.table("client_notifications")\
        .update({"read": True})\
        .eq("client_id", user["sub"])\
        .eq("read", False)\
        .execute()
    return {"message": "ok"}


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

            # Récupérer le nom du commerçant
            merchant_res = supabase.table("merchants").select("business_name, stamps_required").eq("id", merchant_id).execute()
            merchant_name = merchant_res.data[0]["business_name"] if merchant_res.data else ""

            # Récupérer les clients cibles
            cards_res = supabase.table("loyalty_cards")\
                .select("client_id, stamps_count")\
                .eq("merchant_id", merchant_id)\
                .execute()

            client_ids = []
            if filter_type == "broadcast":
                client_ids = [c["client_id"] for c in cards_res.data]
            elif filter_type == "stamps" and filter_value is not None:
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

            # broadcast/stamps = offre, inactive = visite
            sched_cat = "visite" if filter_type == "inactive" else "offre"
            sent = _send_fcm_to_clients(title, message, client_ids, merchant_id, merchant_name, "scheduled", notif_category=sched_cat)
            print(f"✅ Scheduled notif {notif['id']}: {sent} envoyée(s)")

            # Marquer comme envoyée
            supabase.table("scheduled_notifications")\
                .update({"sent": True})\
                .eq("id", notif["id"])\
                .execute()

    except Exception as e:
        print(f"❌ Erreur job scheduler: {e}")
