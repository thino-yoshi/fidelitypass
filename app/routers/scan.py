from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Optional
from app.database import supabase, SECRET_KEY
from app.dependencies import get_current_user
from app.limiter import limiter
from app.logger import get_logger
from jose import jwt, JWTError

logger = get_logger("scan")

router = APIRouter(tags=["Scan"])

class ScanRequest(BaseModel):
    qr_token: str
    amount: Optional[float] = None

class ResolveRequest(BaseModel):
    qr_token: str


@router.post("/resolve")
@limiter.limit("60/minute")
def resolve_qr(request: Request, data: ResolveRequest, user=Depends(get_current_user)):
    """Identifie un QR scanné par le commerçant SANS rien modifier.
    Renvoie kind='reward' (QR de récompense à valider) ou kind='stamp' (carte à tamponner)."""
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    decoded = None
    try:
        decoded = jwt.decode(data.qr_token, SECRET_KEY, algorithms=["HS256"])
    except JWTError:
        pass

    # ── Cas RÉCOMPENSE ──────────────────────────────────────────────────────────
    if decoded and decoded.get("type") == "reward":
        reward_id = decoded.get("reward_id")
        rres = supabase.table("rewards").select("*").eq("id", reward_id).execute()
        if not rres.data:
            raise HTTPException(status_code=404, detail="Récompense introuvable")
        rw = rres.data[0]
        if rw["merchant_id"] != user["sub"]:
            raise HTTPException(status_code=403, detail="Cette récompense n'est pas pour votre commerce")
        if rw.get("redeemed_at"):
            raise HTTPException(status_code=400, detail="Récompense déjà utilisée")
        client_res = supabase.table("users").select("name, email").eq("id", rw["client_id"]).execute()
        client = client_res.data[0] if client_res.data else {}
        return {
            "kind":        "reward",
            "reward_id":   reward_id,
            "qr_token":    data.qr_token,
            "client_name": client.get("name") or client.get("email") or "Client",
            "description": rw.get("description") or "Récompense",
        }

    # ── Cas TAMPON (carte) ──────────────────────────────────────────────────────
    real_qr_token = decoded.get("qr_token", data.qr_token) if decoded else data.qr_token
    res = supabase.table("loyalty_cards").select("*").eq("qr_token", real_qr_token).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="QR code invalide ou expiré")
    card = res.data[0]
    if card["merchant_id"] != user["sub"]:
        raise HTTPException(status_code=403, detail="Cette carte n'appartient pas à votre commerce")

    merchant = supabase.table("merchants").select("*").eq("id", user["sub"]).execute().data[0]
    client_res = supabase.table("users").select("name, email, profile_picture_url").eq("id", card["client_id"]).execute()
    client = client_res.data[0] if client_res.data else {}

    program_type = merchant.get("program_type", "stamps")
    if program_type == "points":
        current_count = card.get("points_count") or 0
        required = merchant.get("points_required") or 100
    else:
        current_count = card.get("stamps_count") or 0
        required = merchant.get("stamps_required") or 10

    return {
        "kind":             "stamp",
        "card_id":          card["id"],
        "client_id":        card["client_id"],
        "client_name":      client.get("name") or client.get("email") or "Client",
        "profile_picture_url": client.get("profile_picture_url"),
        "stamps_count":     current_count,
        "stamps_required":  required,
        "program_type":     program_type,
    }

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

    program_type = merchant.get("program_type", "stamps")

    # ── Mode Points ────────────────────────────────────────────────────────────
    if program_type == "points":
        if data.amount is None or data.amount <= 0:
            raise HTTPException(status_code=400, detail="Le montant de l'achat est requis pour un programme par points")

        points_per_euro = merchant.get("points_per_euro") or 10
        points_required = merchant.get("points_required") or 100
        points_added = round(data.amount * points_per_euro)
        current_points = card.get("points_count") or 0
        new_points = current_points + points_added

        reward_reached = new_points >= points_required
        if reward_reached:
            new_points = 0

        supabase.table("loyalty_cards").update({"points_count": new_points}).eq("id", card["id"]).execute()

        supabase.table("scan_history").insert({
            "merchant_id": user["sub"],
            "client_id": card["client_id"],
            "card_id": card["id"],
            "stamps_count": new_points,
            "reward_reached": reward_reached,
        }).execute()

        if reward_reached:
            notif_title = "🎉 Récompense débloquée !"
            notif_body = f"Bravo ! Tu as gagné ta récompense chez {merchant['business_name']}."
            notif_type = "recompense"
        else:
            remaining = points_required - new_points
            notif_title = "⭐ Points ajoutés !"
            notif_body = f"+{points_added} pts · {new_points}/{points_required} points. Plus que {remaining} pour ta récompense !"
            notif_type = "points"

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
            logger.info(f"REWARD(pts) merchant={user['sub']} client={card['client_id']} added={points_added}")
        else:
            logger.info(f"SCAN(pts) merchant={user['sub']} client={card['client_id']} points={new_points}/{points_required}")

        return {
            "success": True,
            "points_count": new_points,
            "points_required": points_required,
            "points_added": points_added,
            "reward_reached": reward_reached,
            "message": "🎉 Récompense débloquée !" if reward_reached else f"+{points_added} pts ! {new_points}/{points_required}",
        }

    # ── Mode Tampons (défaut) ──────────────────────────────────────────────────
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
        "message": "🎉 Récompense débloquée !" if reward_reached else f"Tampon ajouté ! {new_count}/{merchant['stamps_required']}",
    }
