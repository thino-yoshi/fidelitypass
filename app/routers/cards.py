from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel
from app.database import supabase, SECRET_KEY
from app.dependencies import get_current_user
from jose import jwt
import uuid
import csv
import io
import os
import json as json_lib
import time
import hashlib
import zipfile
import base64
from datetime import datetime, timedelta, timezone

router = APIRouter(tags=["Cards"])

class CreateCardRequest(BaseModel):
    merchant_id: str

class JoinMerchantRequest(BaseModel):
    static_qr_token: str

@router.post("/join")
def join_via_static_qr(data: JoinMerchantRequest, user=Depends(get_current_user)):
    if user.get("user_type", "client") != "client":
        raise HTTPException(status_code=403, detail="Réservé aux clients")

    merchant_res = supabase.table("merchants")\
        .select("id, business_name, category, stamps_required, reward_description")\
        .eq("static_qr_token", data.static_qr_token)\
        .execute()
    if not merchant_res.data:
        raise HTTPException(status_code=404, detail="QR code invalide")

    merchant = merchant_res.data[0]
    merchant_id = merchant["id"]

    existing = supabase.table("loyalty_cards")\
        .select("*")\
        .eq("client_id", user["sub"])\
        .eq("merchant_id", merchant_id)\
        .execute()

    if existing.data:
        return {"already_member": True, "card": existing.data[0], "merchant": merchant}

    # ── Auto-sync auth.users → public.users si manquant ───────────────────────
    # public.users a des colonnes NOT NULL : email, password_hash, user_type, name
    # On fournit des valeurs par défaut pour éviter les violations de contraintes.
    user_email = user.get("email") or f"user-{user['sub'][:8]}@qarta.local"
    user_name = user_email.split("@")[0] if "@" in user_email else "Client"

    try:
        # Vérifier si l'utilisateur existe déjà dans public.users
        existing_user = supabase.table("users").select("id").eq("id", user["sub"]).execute()
        if not existing_user.data:
            supabase.table("users").insert({
                "id": user["sub"],
                "email": user_email,
                "user_type": "client",
                "name": user_name,
                "password_hash": "SUPABASE_AUTH",  # géré par Supabase Auth, pas par nous
            }).execute()
    except Exception as e:
        # Logger l'erreur complète pour debugging
        raise HTTPException(
            status_code=500,
            detail=f"Erreur création profil utilisateur : {type(e).__name__}: {str(e)}"
        )

    # ── Créer la carte de fidélité ─────────────────────────────────────────────
    try:
        qr_token = str(uuid.uuid4())
        card = supabase.table("loyalty_cards").insert({
            "client_id": user["sub"],
            "merchant_id": merchant_id,
            "stamps_count": 0,
            "qr_token": qr_token,
        }).execute()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur création carte : {type(e).__name__}: {str(e)}"
        )

    return {"already_member": False, "card": card.data[0], "merchant": merchant}

@router.post("/")
def create_card(data: CreateCardRequest, user=Depends(get_current_user)):
    client_id = user["sub"]
    existing = supabase.table("loyalty_cards").select("id").eq("client_id", client_id).eq("merchant_id", data.merchant_id).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Carte déjà existante pour ce commerce")
    qr_token = str(uuid.uuid4())
    card = supabase.table("loyalty_cards").insert({
        "client_id": client_id,
        "merchant_id": data.merchant_id,
        "stamps_count": 0,
        "qr_token": qr_token
    }).execute()
    return card.data[0]

@router.get("/me")
def get_my_cards(user=Depends(get_current_user), limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    client_id = user["sub"]
    cards = supabase.table("loyalty_cards").select(
        "*, merchants(business_name, category, stamps_required, reward_description, program_type, "
        "points_per_euro, points_required, address, phone, opening_hours, opening_days, website, description)"
    ).eq("client_id", client_id).range(offset, offset + limit - 1).execute()

    if not cards.data:
        return []

    # Récupérer les designs de cartes pour tous les commerçants en une seule requête
    merchant_ids = list({c["merchant_id"] for c in cards.data if c.get("merchant_id")})
    designs: dict = {}
    if merchant_ids:
        try:
            design_res = supabase.table("merchant_card_designs") \
                .select("merchant_id, card_design") \
                .in_("merchant_id", merchant_ids) \
                .execute()
            designs = {d["merchant_id"]: d["card_design"] for d in (design_res.data or [])}
        except Exception:
            pass  # Pas bloquant si la table n'existe pas encore

    # Embarquer le design dans chaque carte
    for card in cards.data:
        mid = card.get("merchant_id")
        card["card_design"] = designs.get(mid)  # None si aucun design

    # Récupérer le dernier scan par carte (une seule requête bulk)
    card_ids = [c["id"] for c in cards.data]
    last_scan_map: dict = {}
    if card_ids:
        try:
            scan_res = supabase.table("scan_history") \
                .select("card_id, scanned_at") \
                .in_("card_id", card_ids) \
                .order("scanned_at", desc=True) \
                .execute()
            for s in (scan_res.data or []):
                cid = s["card_id"]
                if cid not in last_scan_map:
                    last_scan_map[cid] = s["scanned_at"]
        except Exception:
            pass

    for card in cards.data:
        card["last_scan_at"] = last_scan_map.get(card["id"])  # None si jamais scannée

    # Trier : dernière utilisée en premier, jamais scannées à la fin
    cards.data.sort(key=lambda c: c.get("last_scan_at") or "", reverse=True)

    return cards.data

@router.get("/qr/{card_id}")
def get_dynamic_qr(card_id: str, user=Depends(get_current_user)):
    # Vérifier que la carte appartient bien à ce client
    card = supabase.table("loyalty_cards").select("*").eq("id", card_id).eq("client_id", user["sub"]).execute()
    if not card.data:
        raise HTTPException(status_code=404, detail="Carte non trouvée")
    
    # Générer un token JWT qui expire dans 60s
    payload = {
        "qr_token": card.data[0]["qr_token"],
        "card_id": card_id,
        "exp": datetime.utcnow() + timedelta(seconds=60)
    }
    dynamic_token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")

    return {"dynamic_token": dynamic_token, "expires_in": 60}

@router.get("/my-history")
def get_client_history(user=Depends(get_current_user)):
    if user.get("user_type", "client") != "client":
        raise HTTPException(status_code=403, detail="Réservé aux clients")

    res = supabase.table("scan_history")\
        .select("*")\
        .eq("client_id", user["sub"])\
        .order("scanned_at", desc=True)\
        .limit(100)\
        .execute()

    # Batch-fetch merchants (évite N requêtes)
    merchant_ids = list({s["merchant_id"] for s in (res.data or [])})
    merchant_map: dict = {}
    if merchant_ids:
        m_res = supabase.table("merchants")\
            .select("id, business_name, category, program_type, points_required")\
            .in_("id", merchant_ids)\
            .execute()
        for m in (m_res.data or []):
            merchant_map[m["id"]] = m

    # Calcul du delta par carte (ordre croissant → différence consécutive)
    scans_asc = sorted(res.data or [], key=lambda x: x.get("scanned_at") or "")
    prev_by_card: dict = {}
    for scan in scans_asc:
        merchant = merchant_map.get(scan["merchant_id"], {})
        scan["merchant"] = merchant
        program_type = merchant.get("program_type", "stamps")
        if program_type == "points":
            points_required = merchant.get("points_required") or 100
            prev  = prev_by_card.get(scan["card_id"], 0)
            curr  = scan.get("stamps_count") or 0
            if scan.get("reward_reached"):
                delta = max(0, (points_required - prev) + curr)
            else:
                delta = max(0, curr - prev)
            scan["delta"] = delta
            prev_by_card[scan["card_id"]] = curr
        else:
            scan["delta"] = 1

    # Retour dans l'ordre décroissant (plus récent en premier)
    return sorted(res.data or [], key=lambda x: x.get("scanned_at") or "", reverse=True)


@router.get("/scan-history")
def get_scan_history(user=Depends(get_current_user)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    res = supabase.table("scan_history")\
        .select("*")\
        .eq("merchant_id", user["sub"])\
        .order("scanned_at", desc=True)\
        .limit(50)\
        .execute()

    results = []
    for scan in res.data:
        client_res = supabase.table("users")\
            .select("name, email")\
            .eq("id", scan["client_id"])\
            .execute()
        client = client_res.data[0] if client_res.data else {}
        scan["client"] = client
        results.append(scan)

    return results

@router.get("/clients")
def get_merchant_clients(user=Depends(get_current_user), limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    cards_res = supabase.table("loyalty_cards")\
        .select("*")\
        .eq("merchant_id", user["sub"])\
        .range(offset, offset + limit - 1)\
        .execute()

    results = []
    for card in cards_res.data:
        client_res = supabase.table("users")\
            .select("name, email, profile_picture_url")\
            .eq("id", card["client_id"])\
            .execute()
        client = client_res.data[0] if client_res.data else {}
        card["client"] = client
        results.append(card)

    return results


@router.get("/{card_id}/poll")
def poll_stamp(card_id: str, user=Depends(get_current_user)):
    """Polling léger côté client : retourne l'état actuel + horodatage du dernier scan.
    Le client compare le scanned_at au timestamp d'ouverture du QR modal pour détecter
    un nouveau tampon — fiable même si points_count boucle sur la même valeur."""
    if user["user_type"] != "client":
        raise HTTPException(status_code=403, detail="Réservé aux clients")

    card_res = supabase.table("loyalty_cards")\
        .select("id, stamps_count, points_count, merchant_id")\
        .eq("id", card_id)\
        .eq("client_id", user["sub"])\
        .execute()
    if not card_res.data:
        raise HTTPException(status_code=404, detail="Carte non trouvée")
    card = card_res.data[0]

    scan_res = supabase.table("scan_history")\
        .select("stamps_count, reward_reached, scanned_at")\
        .eq("card_id", card_id)\
        .order("scanned_at", desc=True)\
        .limit(1)\
        .execute()
    latest = scan_res.data[0] if scan_res.data else None

    return {
        "stamps_count": card.get("stamps_count") or 0,
        "points_count": card.get("points_count") or 0,
        "latest_scan_at":        latest["scanned_at"]     if latest else None,
        "latest_reward_reached": latest.get("reward_reached", False) if latest else False,
    }


class AdjustStampRequest(BaseModel):
    delta: int  # ex: +1, +3 (ajout) ou -1 (retrait)


@router.post("/{card_id}/adjust-stamp")
def adjust_stamp(card_id: str, data: AdjustStampRequest, user=Depends(get_current_user)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    # Retrait : -1 uniquement. Ajout : jusqu'à 20 tampons (mode stamps) ou
    # jusqu'à 100 000 points (mode points — ex: 10 000 € × 10 pts/€).
    if data.delta == 0 or data.delta < -1:
        raise HTTPException(status_code=400, detail="delta invalide (0 interdit, retrait = -1 uniquement)")
    if data.delta > 100_000:
        raise HTTPException(status_code=400, detail="delta trop élevé (max 100 000)")

    card_res = supabase.table("loyalty_cards")\
        .select("*")\
        .eq("id", card_id)\
        .eq("merchant_id", user["sub"])\
        .execute()
    if not card_res.data:
        raise HTTPException(status_code=404, detail="Carte non trouvée")

    card = card_res.data[0]
    merchant_res = supabase.table("merchants").select("stamps_required, points_required, points_per_euro, reward_description, program_type").eq("id", user["sub"]).execute()
    merchant = merchant_res.data[0] if merchant_res.data else {}
    program_type = merchant.get("program_type") or "stamps"
    reward_desc = merchant.get("reward_description") or "Récompense"

    if program_type == "points":
        count_field = "points_count"
        required = merchant.get("points_required") or 100
        # Mode tampons : cap à 20 par ajout manuel
    else:
        count_field = "stamps_count"
        required = merchant.get("stamps_required") or 10
        if data.delta > 20:
            raise HTTPException(status_code=400, detail="delta doit être entre 1 et 20 pour un programme tampons")

    new_total = (card.get(count_field) or 0) + data.delta
    if new_total < 0:
        new_total = 0

    # Récompense atteinte si l'ajout fait franchir le seuil. Chaque carte complétée
    # crée une récompense (portefeuille) ; le reste repart sur une carte vierge.
    reward_reached = data.delta > 0 and new_total >= required
    completions = 0
    if reward_reached:
        completions = new_total // required
        new_count = new_total % required  # surplus reporté sur la prochaine carte
        reward_rows = [{
            "client_id": card["client_id"],
            "merchant_id": user["sub"],
            "description": reward_desc,
        } for _ in range(completions)]
        if reward_rows:
            supabase.table("rewards").insert(reward_rows).execute()
    else:
        new_count = min(new_total, required)

    supabase.table("loyalty_cards").update({count_field: new_count}).eq("id", card_id).execute()

    supabase.table("scan_history").insert({
        "merchant_id": user["sub"],
        "client_id": card["client_id"],
        "card_id": card_id,
        "stamps_count": new_count,
        "reward_reached": reward_reached,
        "manual": True,
    }).execute()

    return {
        "success": True,
        "stamps_count": new_count,
        "stamps_required": required,
        "reward_reached": reward_reached,
        "rewards_earned": completions,
    }


class ClientNoteRequest(BaseModel):
    note: str = ""


@router.post("/{card_id}/note")
def set_client_note(card_id: str, data: ClientNoteRequest, user=Depends(get_current_user)):
    """Note privée du commerçant sur un client (stockée sur sa carte de fidélité)."""
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    card_res = supabase.table("loyalty_cards")\
        .select("id")\
        .eq("id", card_id)\
        .eq("merchant_id", user["sub"])\
        .execute()
    if not card_res.data:
        raise HTTPException(status_code=404, detail="Carte non trouvée")

    supabase.table("loyalty_cards").update({"merchant_note": data.note.strip()}).eq("id", card_id).execute()
    return {"success": True, "merchant_note": data.note.strip()}


@router.get("/export-csv")
def export_clients_csv(user=Depends(get_current_user)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    merchant_res = supabase.table("merchants").select("stamps_required").eq("id", user["sub"]).execute()
    stamps_required = merchant_res.data[0]["stamps_required"] if merchant_res.data else 10

    cards_res = supabase.table("loyalty_cards").select("*").eq("merchant_id", user["sub"]).execute()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Nom", "Email", "Tampons", "Tampons requis", "Tampons restants", "Date inscription"])

    for card in cards_res.data:
        client_res = supabase.table("users").select("name, email").eq("id", card["client_id"]).execute()
        client = client_res.data[0] if client_res.data else {}
        stamps = card["stamps_count"]
        created = card.get("created_at", "")[:10] if card.get("created_at") else ""
        writer.writerow([
            client.get("name", ""),
            client.get("email", ""),
            stamps,
            stamps_required,
            max(0, stamps_required - stamps),
            created,
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=clients.csv"},
    )


@router.get("/stats/daily")
def get_daily_stats(user=Depends(get_current_user)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    since = (datetime.now(timezone.utc) - timedelta(days=29)).isoformat()

    # Scans par jour
    scan_res = supabase.table("scan_history")\
        .select("scanned_at")\
        .eq("merchant_id", user["sub"])\
        .gte("scanned_at", since)\
        .execute()

    # Récompenses utilisées (redeemed) par jour — pas les atteintes non utilisées
    reward_res = supabase.table("rewards")\
        .select("redeemed_at")\
        .eq("merchant_id", user["sub"])\
        .gte("redeemed_at", since)\
        .execute()

    daily: dict = {}
    for scan in (scan_res.data or []):
        day = scan["scanned_at"][:10]
        if day not in daily:
            daily[day] = {"scans": 0, "rewards": 0}
        daily[day]["scans"] += 1

    for reward in (reward_res.data or []):
        if not reward.get("redeemed_at"):
            continue
        day = reward["redeemed_at"][:10]
        if day not in daily:
            daily[day] = {"scans": 0, "rewards": 0}
        daily[day]["rewards"] += 1

    result = []
    for i in range(30):
        day = (datetime.now(timezone.utc) - timedelta(days=29 - i)).strftime("%Y-%m-%d")
        d = daily.get(day, {"scans": 0, "rewards": 0})
        result.append({"date": day, "scans": d["scans"], "rewards": d["rewards"]})

    return result


@router.get("/stats")
def get_merchant_stats(user=Depends(get_current_user)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    cards_res = supabase.table("loyalty_cards")\
        .select("*")\
        .eq("merchant_id", user["sub"])\
        .execute()

    cards = cards_res.data
    total_clients = len(cards)
    total_stamps = sum(c["stamps_count"] for c in cards)

    rewards_res = supabase.table("scan_history")\
        .select("id")\
        .eq("merchant_id", user["sub"])\
        .eq("reward_reached", True)\
        .execute()
    total_rewards = len(rewards_res.data)

    scans_res = supabase.table("scan_history")\
        .select("id")\
        .eq("merchant_id", user["sub"])\
        .execute()
    total_scans = len(scans_res.data)

    return {
        "total_clients": total_clients,
        "total_stamps": total_stamps,
        "total_rewards": total_rewards,
        "total_scans": total_scans,
    }


# ══════════════════════════════════════════════════════════════════════════════
# WALLET — Google Wallet (Android) + Apple Wallet (iOS)
# ══════════════════════════════════════════════════════════════════════════════

# 1×1 transparent PNG utilisé comme icône placeholder pour le .pkpass
_ICON_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


def _hex_to_rgb(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return "rgb(26, 26, 46)"
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgb({r}, {g}, {b})"


def _card_primary_color(merchant: dict) -> str:
    try:
        design = json_lib.loads(merchant.get("card_design") or "{}")
        colors = design.get("bgColors", [])
        hex_c = colors[0] if colors else "#1a1a2e"
        return hex_c if hex_c.startswith("#") else f"#{hex_c}"
    except Exception:
        return "#1a1a2e"


def _gw_sign_jwt(payload: dict, sa_email: str, private_key_pem: str) -> str:
    """Signe un JWT Google Wallet avec RS256 via google-auth (lib officielle)."""
    import google.auth.crypt
    import google.auth.jwt

    signer = google.auth.crypt.RSASigner.from_string(private_key_pem, sa_email)
    token = google.auth.jwt.encode(signer, payload)
    return token.decode("utf-8") if isinstance(token, bytes) else token


# ── 1. Google Wallet JWT ───────────────────────────────────────────────────────

@router.get("/{card_id}/wallet/google")
def get_google_wallet_jwt(card_id: str, user=Depends(get_current_user)):
    """Retourne un JWT signé à passer à pay.google.com/gp/v/save/{jwt}."""
    issuer_id   = os.getenv("GW_ISSUER_ID", "")
    sa_email    = os.getenv("GW_SA_EMAIL", "")
    private_key = os.getenv("GW_PRIVATE_KEY", "").replace("\\n", "\n")

    if not issuer_id or not sa_email or not private_key:
        raise HTTPException(
            status_code=503,
            detail="Google Wallet non configuré — ajoutez GW_ISSUER_ID, GW_SA_EMAIL, GW_PRIVATE_KEY dans Railway"
        )

    card_res = supabase.table("loyalty_cards")\
        .select("*, merchants(business_name, stamps_required, points_required, reward_description, program_type)")\
        .eq("id", card_id).eq("client_id", user["sub"]).execute()
    if not card_res.data:
        raise HTTPException(status_code=404, detail="Carte non trouvée")

    card     = card_res.data[0]
    merchant = card["merchants"]

    try:
        design_res = supabase.table("merchant_card_designs")\
            .select("card_design").eq("merchant_id", card["merchant_id"]).execute()
        merchant["card_design"] = design_res.data[0]["card_design"] if design_res.data else None
    except Exception:
        merchant["card_design"] = None

    is_points = merchant.get("program_type") == "points"
    count    = (card.get("points_count") if is_points else card.get("stamps_count")) or 0
    goal     = (merchant.get("points_required") if is_points else merchant.get("stamps_required")) or 10
    hex_color = _card_primary_color(merchant)

    mk = card["merchant_id"].replace("-", "")
    ck = card_id.replace("-", "")
    class_id  = f"{issuer_id}.loyalty{mk}"
    object_id = f"{issuer_id}.loyalty{ck}"

    # ── Authentification service account ──────────────────────────────────────
    from google.oauth2 import service_account as sa_mod
    import google.auth.transport.requests as ga_requests
    import httpx

    sa_info = {
        "type": "service_account",
        "client_email": sa_email,
        "private_key": private_key,
        "private_key_id": "key",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    creds = sa_mod.Credentials.from_service_account_info(
        sa_info,
        scopes=["https://www.googleapis.com/auth/wallet_object.issuer"],
    )
    creds.refresh(ga_requests.Request())
    auth_headers = {
        "Authorization": f"Bearer {creds.token}",
        "Content-Type": "application/json",
    }

    gw_base = "https://walletobjects.googleapis.com/walletobjects/v1"

    logo_url = os.getenv(
        "GW_LOGO_URL",
        "https://fidelitypass-production.up.railway.app/app-logo.png",
    )
    loyalty_class = {
        "id": class_id,
        "issuerName": "Qarta",
        "programName": merchant["business_name"],
        "reviewStatus": "UNDER_REVIEW",
        "hexBackgroundColor": hex_color,
        "countryCode": "BE",
        "programLogo": {
            "sourceUri": {"uri": logo_url},
            "contentDescription": {
                "defaultValue": {"language": "fr", "value": "Qarta"}
            },
        },
    }
    loyalty_object = {
        "id": object_id,
        "classId": class_id,
        "state": "ACTIVE",
        "accountId": user["sub"],
        "accountName": user.get("name", "Client"),
        "loyaltyPoints": {
            "balance": {"string": f"{count}/{goal}"},
            "label": "Points" if is_points else "Tampons",
        },
        "barcode": {"type": "QR_CODE", "value": card["qr_token"], "alternateText": ""},
        "hexBackgroundColor": hex_color,
    }

    with httpx.Client(timeout=15) as http:
        # Classe : créer si absente, mettre à jour sinon
        r = http.get(f"{gw_base}/loyaltyClass/{class_id}", headers=auth_headers)
        if r.status_code == 404:
            r = http.post(f"{gw_base}/loyaltyClass", json=loyalty_class, headers=auth_headers)
        else:
            r = http.put(f"{gw_base}/loyaltyClass/{class_id}", json=loyalty_class, headers=auth_headers)
        if r.status_code not in (200, 201):
            raise HTTPException(status_code=502, detail=f"GW class error {r.status_code}: {r.text[:300]}")

        # Objet : créer si absent, patcher sinon
        r = http.get(f"{gw_base}/loyaltyObject/{object_id}", headers=auth_headers)
        if r.status_code == 404:
            r = http.post(f"{gw_base}/loyaltyObject", json=loyalty_object, headers=auth_headers)
        else:
            r = http.patch(f"{gw_base}/loyaltyObject/{object_id}", json=loyalty_object, headers=auth_headers)
        if r.status_code not in (200, 201):
            raise HTTPException(status_code=502, detail=f"GW object error {r.status_code}: {r.text[:300]}")

    # JWT minimal qui référence l'objet existant
    gw_payload = {
        "iss": sa_email,
        "aud": "google",
        "typ": "savetowallet",
        "iat": int(time.time()),
        "payload": {"loyaltyObjects": [{"id": object_id}]},
        "origins": [],
    }

    token = _gw_sign_jwt(gw_payload, sa_email, private_key)
    return {"jwt": token, "save_url": f"https://pay.google.com/gp/v/save/{token}"}


# ── 2. Apple Wallet — URL signée (appelée par le client Flutter avec auth) ────

@router.get("/{card_id}/wallet/apple-url")
def get_apple_wallet_url(card_id: str, user=Depends(get_current_user)):
    """Génère une URL .pkpass temporaire (5 min) pour iOS Safari."""
    card_res = supabase.table("loyalty_cards").select("id")\
        .eq("id", card_id).eq("client_id", user["sub"]).execute()
    if not card_res.data:
        raise HTTPException(status_code=404, detail="Carte non trouvée")

    token = jwt.encode({
        "card_id": card_id,
        "client_id": user["sub"],
        "exp": datetime.utcnow() + timedelta(minutes=5),
    }, SECRET_KEY, algorithm="HS256")

    base = os.getenv("API_BASE_URL", "https://fidelitypass-production.up.railway.app")
    return {"url": f"{base}/cards/{card_id}/wallet/apple?t={token}"}


# ── 3. Apple Wallet — génère le .pkpass (accès par token temporaire) ──────────

@router.get("/{card_id}/wallet/apple")
def get_apple_wallet_pass(card_id: str, t: str = Query(...)):
    """Retourne le fichier .pkpass pour iOS (signé si certificat configuré)."""
    try:
        payload = jwt.decode(t, SECRET_KEY, algorithms=["HS256"])
        if payload.get("card_id") != card_id:
            raise ValueError("card_id mismatch")
        client_id = payload["client_id"]
    except Exception:
        raise HTTPException(status_code=401, detail="Token invalide ou expiré")

    card_res = supabase.table("loyalty_cards")\
        .select("*, merchants(business_name, stamps_required, points_required, reward_description, program_type)")\
        .eq("id", card_id).eq("client_id", client_id).execute()
    if not card_res.data:
        raise HTTPException(status_code=404, detail="Carte non trouvée")

    card     = card_res.data[0]
    merchant = card["merchants"]

    try:
        design_res = supabase.table("merchant_card_designs")\
            .select("card_design").eq("merchant_id", card["merchant_id"]).execute()
        merchant["card_design"] = design_res.data[0]["card_design"] if design_res.data else None
    except Exception:
        merchant["card_design"] = None

    is_points = merchant.get("program_type") == "points"
    count    = (card.get("points_count") if is_points else card.get("stamps_count")) or 0
    goal     = (merchant.get("points_required") if is_points else merchant.get("stamps_required")) or 10
    hex_color = _card_primary_color(merchant)

    pass_type_id = os.getenv("AW_PASS_TYPE_ID", "pass.com.qarta.loyalty")
    team_id      = os.getenv("AW_TEAM_ID", "XXXXXXXXXX")

    pass_dict = {
        "formatVersion": 1,
        "passTypeIdentifier": pass_type_id,
        "serialNumber": card_id,
        "teamIdentifier": team_id,
        "organizationName": "Qarta",
        "description": f"Carte fidélité {merchant['business_name']}",
        "logoText": merchant["business_name"],
        "backgroundColor": _hex_to_rgb(hex_color),
        "foregroundColor": "rgb(255, 255, 255)",
        "labelColor": "rgb(180, 180, 200)",
        "storeCard": {
            "primaryFields": [{
                "key": "balance",
                "label": "Points" if is_points else "Tampons",
                "value": f"{count}/{goal}",
            }],
            "auxiliaryFields": [{
                "key": "reward",
                "label": "Récompense",
                "value": merchant.get("reward_description", ""),
            }],
        },
        "barcodes": [{
            "message": card["qr_token"],
            "format": "PKBarcodeFormatQR",
            "messageEncoding": "iso-8859-1",
        }],
    }

    pass_bytes = json_lib.dumps(pass_dict, ensure_ascii=False, indent=2).encode("utf-8")

    files: dict[str, bytes] = {
        "pass.json":  pass_bytes,
        "icon.png":   _ICON_PNG,
        "icon@2x.png": _ICON_PNG,
    }
    manifest = {name: hashlib.sha1(data).hexdigest() for name, data in files.items()}
    manifest_bytes = json_lib.dumps(manifest).encode("utf-8")
    files["manifest.json"] = manifest_bytes

    # Signature (optionnel — nécessite AW_CERT_PEM + AW_KEY_PEM + AW_WWDR_PEM dans Railway)
    cert_pem = os.getenv("AW_CERT_PEM", "").replace("\\n", "\n")
    key_pem  = os.getenv("AW_KEY_PEM",  "").replace("\\n", "\n")
    wwdr_pem = os.getenv("AW_WWDR_PEM", "").replace("\\n", "\n")

    if cert_pem and key_pem:
        try:
            from cryptography.hazmat.primitives import serialization, hashes as cr_hashes
            from cryptography import x509
            from cryptography.hazmat.primitives.serialization import pkcs7 as pkcs7_ser

            cert = x509.load_pem_x509_certificate(cert_pem.encode())
            key  = serialization.load_pem_private_key(key_pem.encode(), password=None)
            builder = pkcs7_ser.PKCS7SignatureBuilder()\
                .set_data(manifest_bytes)\
                .add_signer(cert, key, cr_hashes.SHA256())
            if wwdr_pem:
                builder = builder.add_certificate(
                    x509.load_pem_x509_certificate(wwdr_pem.encode())
                )
            files["signature"] = builder.sign(
                serialization.Encoding.DER,
                [pkcs7_ser.PKCS7Options.DetachedSignature],
            )
        except Exception:
            pass  # Pass sans signature → iOS refusera l'installation mais utile en dev

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)

    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.apple.pkpass",
        headers={"Content-Disposition": f"attachment; filename=qarta_{card_id[:8]}.pkpass"},
    )


@router.delete("/{card_id}")
def delete_card(card_id: str, user=Depends(get_current_user)):
    """Supprime une carte de fidélité appartenant au client connecté."""
    if user.get("user_type") != "client":
        raise HTTPException(status_code=403, detail="Réservé aux clients")

    # Vérifier que la carte appartient bien à ce client
    card_res = supabase.table("loyalty_cards")\
        .select("id, merchant_id")\
        .eq("id", card_id)\
        .eq("client_id", user["sub"])\
        .execute()

    if not card_res.data:
        raise HTTPException(status_code=404, detail="Carte non trouvée")

    merchant_id = card_res.data[0]["merchant_id"]

    # Supprimer l'historique de scan lié
    supabase.table("scan_history").delete().eq("card_id", card_id).execute()

    # Supprimer les récompenses non utilisées liées à cette carte (client + commerçant)
    supabase.table("rewards")\
        .delete()\
        .eq("client_id", user["sub"])\
        .eq("merchant_id", merchant_id)\
        .is_("redeemed_at", "null")\
        .execute()

    # Supprimer la carte
    supabase.table("loyalty_cards").delete().eq("id", card_id).execute()

    return {"message": "Carte supprimée"}